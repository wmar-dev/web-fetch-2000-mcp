# Live benchmark snapshot

Generated 2026-10-08 19:33:01 with 3 rounds per URL.

- **SC-001** usable content on first visit: 100% (target >= 90%)
- **SC-002** first strategy succeeded after warm-up: 100% (target >= 90%)
- **SC-003** repeat-fetch speed-up for sites needing a heavier strategy: 28% (target >= 50%)

| round | url | kind | ok | strategy | attempts | seconds |
|---|---|---|---|---|---|---|
| 1 | https://example.com/ | static | True | browser | http > browser | 2.08 |
| 1 | https://en.wikipedia.org/wiki/Web_scraping | static | True | http | http | 0.13 |
| 1 | https://quotes.toscrape.com/ | static | True | http | http | 0.45 |
| 1 | https://quotes.toscrape.com/js/ | javascript | True | browser | http > browser | 1.46 |
| 1 | https://quotes.toscrape.com/scroll | javascript | True | browser | http > browser | 1.52 |
| 1 | https://nowsecure.nl/ | protected (optional) | False | all_strategies_failed | http > browser > stealth | 26.0 |
| 2 | https://example.com/ | static | True | browser | http > browser | 0.76 |
| 2 | https://en.wikipedia.org/wiki/Web_scraping | static | True | http | http | 0.14 |
| 2 | https://quotes.toscrape.com/ | static | True | browser | browser | 1.19 |
| 2 | https://quotes.toscrape.com/js/ | javascript | True | browser | browser | 1.29 |
| 2 | https://quotes.toscrape.com/scroll | javascript | True | browser | browser | 1.4 |
| 2 | https://nowsecure.nl/ | protected (optional) | False | all_strategies_failed | http > browser > stealth | 10.31 |
| 3 | https://example.com/ | static | True | browser | browser | 0.7 |
| 3 | https://en.wikipedia.org/wiki/Web_scraping | static | True | http | http | 0.15 |
| 3 | https://quotes.toscrape.com/ | static | True | browser | browser | 1.25 |
| 3 | https://quotes.toscrape.com/js/ | javascript | True | browser | browser | 1.29 |
| 3 | https://quotes.toscrape.com/scroll | javascript | True | browser | browser | 1.42 |
| 3 | https://nowsecure.nl/ | protected (optional) | False | all_strategies_failed | http > browser > stealth | 12.48 |
