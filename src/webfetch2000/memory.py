"""Strategy memory: which strategy works best per site (and per path section)."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .safety import path_prefix
from .store import Store

DAY = 86400.0
PRIOR = 0.5
EMA_ALPHA = 0.3


@dataclass
class StrategyScore:
    strategy: str
    score: float
    successes: float
    failures: float
    observations: int
    mean_duration_ms: float
    last_attempt_at: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "score": round(self.score, 4),
            "successes": round(self.successes, 3),
            "failures": round(self.failures, 3),
            "observations": self.observations,
            "mean_duration_ms": round(self.mean_duration_ms, 1),
            "last_attempt_at": self.last_attempt_at,
        }


@dataclass
class Plan:
    order: list[str]
    start: str
    reason: str
    scope: str = ""  # "" = domain default, else the path prefix whose override applies
    reprobe: str | None = None
    scores: list[StrategyScore] = field(default_factory=list)


class Memory:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self.store = store
        self.settings = settings
        self.rng = rng

    # ------------------------------------------------------------------ writes
    def record(
        self,
        domain: str,
        path: str,
        strategy: str,
        success: bool,
        duration_ms: int,
        now: float | None = None,
    ) -> None:
        """Atomically record one outcome at the domain level and for the path section."""
        now = time.time() if now is None else now
        prefix = path_prefix(path)
        scopes = [""] + ([prefix] if prefix else [])
        with self.store.tx() as c:
            for scope in scopes:
                row = c.execute(
                    "SELECT successes, failures, mean_duration_ms, observations, last_success_at, "
                    "updated_at FROM outcomes WHERE domain=? AND path_prefix=? AND strategy=?",
                    (domain, scope, strategy),
                ).fetchone()
                if row is None:
                    s, f, mean, obs, last_ok = 0.0, 0.0, float(duration_ms), 0, None
                else:
                    factor = self._decay(now - row[5])
                    s, f = row[0] * factor, row[1] * factor
                    mean = row[2] + EMA_ALPHA * (duration_ms - row[2])
                    obs, last_ok = row[3], row[4]
                s += 1.0 if success else 0.0
                f += 0.0 if success else 1.0
                c.execute(
                    "INSERT OR REPLACE INTO outcomes (domain, path_prefix, strategy, successes, "
                    "failures, mean_duration_ms, observations, last_attempt_at, last_success_at, "
                    "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        domain,
                        scope,
                        strategy,
                        s,
                        f,
                        mean,
                        obs + 1,
                        now,
                        now if success else last_ok,
                        now,
                    ),
                )
            if prefix:
                self._prune_prefixes(c, domain)

    def _prune_prefixes(self, c: Any, domain: str) -> None:
        keep = c.execute(
            "SELECT path_prefix FROM outcomes WHERE domain=? AND path_prefix<>'' "
            "GROUP BY path_prefix ORDER BY MAX(updated_at) DESC LIMIT ?",
            (domain, self.settings.max_prefixes_per_domain),
        ).fetchall()
        keep_set = [k[0] for k in keep]
        marks = ",".join("?" * len(keep_set)) or "''"
        c.execute(
            "DELETE FROM outcomes WHERE domain=? AND path_prefix<>'' "
            f"AND path_prefix NOT IN ({marks})",
            (domain, *keep_set),
        )

    def reset(self, domain: str | None = None) -> int:
        """Forget what was learned for one domain (or everything). Returns domains cleared."""
        with self.store.tx() as c:
            if domain is None:
                n = c.execute("SELECT COUNT(DISTINCT domain) FROM outcomes").fetchone()[0]
                c.execute("DELETE FROM outcomes")
            else:
                n = c.execute(
                    "SELECT COUNT(DISTINCT domain) FROM outcomes WHERE domain=?", (domain,)
                ).fetchone()[0]
                c.execute("DELETE FROM outcomes WHERE domain=?", (domain,))
        return int(n)

    # ------------------------------------------------------------------ reads
    def _decay(self, dt: float) -> float:
        return 0.5 ** (max(0.0, dt) / (self.settings.half_life_days * DAY))

    def _rows(self, domain: str, scope: str) -> dict[str, tuple[Any, ...]]:
        with self.store.conn() as c:
            rows = c.execute(
                "SELECT strategy, successes, failures, mean_duration_ms, observations, "
                "last_attempt_at, updated_at FROM outcomes WHERE domain=? AND path_prefix=?",
                (domain, scope),
            ).fetchall()
        return {r[0]: r for r in rows}

    def scores(
        self, domain: str, scope: str, ladder: list[str], now: float | None = None
    ) -> list[StrategyScore]:
        now = time.time() if now is None else now
        rows = self._rows(domain, scope)
        return [self._score(rows.get(name), name, now) for name in ladder]

    def _score(self, row: tuple[Any, ...] | None, name: str, now: float) -> StrategyScore:
        if row is None:
            return StrategyScore(name, PRIOR, 0.0, 0.0, 0, 0.0, None)
        factor = self._decay(now - row[6])
        s, f, obs = row[1] * factor, row[2] * factor, row[4]
        score = (s + 1) / (s + f + 2) if obs >= self.settings.min_observations else PRIOR
        return StrategyScore(name, score, s, f, obs, row[3], row[5])

    def _choose(self, scores: list[StrategyScore]) -> StrategyScore:
        best = max(s.score for s in scores)
        tol = self.settings.score_tolerance
        return next(s for s in scores if s.score >= best - tol - 1e-12)  # cheapest within tol

    @staticmethod
    def _order(ladder: list[str], start: str) -> list[str]:
        i = ladder.index(start)
        return [start] + ladder[i + 1 :] + ladder[:i]  # escalate first, cheaper ones last

    def plan(self, domain: str, path: str, ladder: list[str], now: float | None = None) -> Plan:
        now = time.time() if now is None else now
        if not ladder:
            return Plan([], "", "no strategies enabled")
        dom_rows = self._rows(domain, "")
        if not dom_rows:
            return Plan(
                list(ladder),
                ladder[0],
                "no history for this site",
                scores=[self._score(None, n, now) for n in ladder],
            )
        scores = [self._score(dom_rows.get(n), n, now) for n in ladder]
        chosen = self._choose(scores)
        scope = ""
        reason = (
            f"{chosen.strategy} is the cheapest within {self.settings.score_tolerance} of the "
            f"best score ({max(s.score for s in scores):.2f})"
        )

        prefix = path_prefix(path)
        if prefix:
            pre = self._prefix_scores(domain, prefix, ladder, now)
            if pre is not None:
                pre_chosen = self._choose(pre)
                if pre_chosen.strategy != chosen.strategy:
                    scope, scores, chosen = prefix, pre, pre_chosen
                    reason = f"learned override for {prefix}: {chosen.strategy} works best there"

        order = self._order(ladder, chosen.strategy)
        probe = self._reprobe_candidate(scores, ladder, chosen.strategy, now)
        if probe is not None:
            order = [probe.strategy] + [n for n in order if n != probe.strategy]
            age = (
                "never tried"
                if probe.last_attempt_at is None
                else f"last tried {(now - probe.last_attempt_at) / DAY:.0f} days ago"
            )
            reason = f"re-test cheaper strategy '{probe.strategy}' ({age}); otherwise {reason}"
        return Plan(
            order, chosen.strategy, reason, scope, probe.strategy if probe else None, scores
        )

    def _prefix_scores(
        self, domain: str, prefix: str, ladder: list[str], now: float
    ) -> list[StrategyScore] | None:
        rows = self._rows(domain, prefix)
        if sum(r[4] for r in rows.values()) < self.settings.override_min_observations:
            return None
        return [self._score(rows.get(n), n, now) for n in ladder]

    def _reprobe_candidate(
        self, scores: list[StrategyScore], ladder: list[str], start: str, now: float
    ) -> StrategyScore | None:
        cheaper = [s for s in scores if ladder.index(s.strategy) < ladder.index(start)]
        stale_after = self.settings.reprobe_after_days * DAY
        for s in cheaper:  # cheapest first
            if s.last_attempt_at is None or now - s.last_attempt_at >= stale_after:
                return s
        if cheaper and self.rng() < self.settings.reprobe_probability:
            return cheaper[0]
        return None

    def snapshot(
        self, domain: str, path: str | None, ladder: list[str], now: float | None = None
    ) -> dict[str, Any]:
        now = time.time() if now is None else now
        plan = self.plan(domain, path or "/", ladder, now)
        by_name = {s.strategy: s for s in (plan.scores or self.scores(domain, "", ladder, now))}
        ranking = [by_name[n].as_dict() for n in plan.order if n in by_name]
        overrides = []
        dom_plan = self.plan(domain, "/", ladder, now)
        with self.store.conn() as c:
            prefixes = [
                r[0]
                for r in c.execute(
                    "SELECT DISTINCT path_prefix FROM outcomes WHERE domain=? AND path_prefix<>''",
                    (domain,),
                )
            ]
        for prefix in sorted(prefixes):
            sc = self._prefix_scores(domain, prefix, ladder, now)
            if sc is None:
                continue
            chosen = self._choose(sc)
            if dom_plan.start and chosen.strategy != dom_plan.start:
                order = self._order(ladder, chosen.strategy)
                by = {s.strategy: s for s in sc}
                overrides.append(
                    {"path_prefix": prefix, "ranking": [by[n].as_dict() for n in order]}
                )
        return {
            "domain": domain,
            "ranking": ranking,
            "overrides": overrides,
            "next_start_strategy": plan.start or None,
            "reason": plan.reason,
        }
