# Changelog

## [1.697.1](https://github.com/plasmonized/containerized-mioty-service-center/compare/v1.697.0...v1.697.1) (2026-08-04)


### Bug Fixes

* align docs artifact path with custom outDir in vitepress config ([b2b2b21](https://github.com/plasmonized/containerized-mioty-service-center/commit/b2b2b21ae868873c9745466ea1dbb137b2bd8b04))
* correct action versions and remove pip cache for uv-based jobs ([233af28](https://github.com/plasmonized/containerized-mioty-service-center/commit/233af28e5498ab3300186f4dc25a3eb5ca3252bb))

## [1.697.0](https://github.com/plasmonized/containerized-mioty-service-center/compare/v1.696.0...v1.697.0) (2026-07-25)


### Features

* add Docker release workflow for manual releases ([0ce2784](https://github.com/plasmonized/containerized-mioty-service-center/commit/0ce2784941ab988166c1107cc5067e44f9d53bc7))
* add python-clean-code and python-testing skills with test infrastructure ([8aaf7ae](https://github.com/plasmonized/containerized-mioty-service-center/commit/8aaf7ae1b09aeb44fd060ce67dace786b5ec7987))
* add remaining agent skills (commit-context, commit-history, forget, handoff, recall, recap, remember, session-history) and skills-lock.json ([18ee8d8](https://github.com/plasmonized/containerized-mioty-service-center/commit/18ee8d8d4950ae3fe2fe4766617086b25347ce50))
* add standardized error codes for key failure paths ([a82d6b3](https://github.com/plasmonized/containerized-mioty-service-center/commit/a82d6b35b82e7e81b7a82da98686c188f19ceb38))
* consolidate Docker volumes into structured directories (certs, config, data, logs) ([9a3e794](https://github.com/plasmonized/containerized-mioty-service-center/commit/9a3e7945708d63f6ddffed4b24578a1fb85bfaa4))
* docker imge creation added ([ac3c583](https://github.com/plasmonized/containerized-mioty-service-center/commit/ac3c58341febd384d2998a3ea26d55a13e0c01cd))
* **docs:** markdown documentation published using vitepress ([a081ac8](https://github.com/plasmonized/containerized-mioty-service-center/commit/a081ac81d84811492c5b170cef3a92166daa5621))
* harden state access and add connection timeline tracing ([ee7aa57](https://github.com/plasmonized/containerized-mioty-service-center/commit/ee7aa5716368fea64969abceabc6fedfb3c8801a))
* introduce Release Please for automated versioning and Docker releases ([c283adb](https://github.com/plasmonized/containerized-mioty-service-center/commit/c283adba4d37a0c7a0e4d306932f7b0f27945bf4))
* introduce structured utc logging foundation ([3cc89d9](https://github.com/plasmonized/containerized-mioty-service-center/commit/3cc89d900610448f0a0c842d1b364bd749bcc3b2))
* **scaci:** v1.690 — SCACI Interface SC↔AC (Task [#2](https://github.com/plasmonized/containerized-mioty-service-center/issues/2)) ([91c852e](https://github.com/plasmonized/containerized-mioty-service-center/commit/91c852ea4f663b558b416a5491219f8f1c7c854d))
* **scaci:** v1.690 — SCACI Interface SC↔AC vollständig implementiert ([0ab67e3](https://github.com/plasmonized/containerized-mioty-service-center/commit/0ab67e3d806d3542ef055194fc446f13c5109bb4))
* **scaci:** v1.690 — SCACI Interface SC↔AC vollständig implementiert ([ce2d8a4](https://github.com/plasmonized/containerized-mioty-service-center/commit/ce2d8a432cc33d5614888f37af197105cf51b8d9))
* **scaci:** v1.690 — SCACI Interface SC↔AC, vollständig verdrahtet ([960ad6f](https://github.com/plasmonized/containerized-mioty-service-center/commit/960ad6f97979f9cf6c06f35d781d6924abbb63c1))
* **scaci:** v1.691 — AC→BS Downlink-Pfad vollständig + einmalige dlDataRes-Bestätigung ([65def47](https://github.com/plasmonized/containerized-mioty-service-center/commit/65def47e228c4db0b9e1bd08d942ba7873d5df9a))
* **v1.691:** AC-Zertifikate über Web-UI erzeugen und herunterladen (App-Centers-Seite) ([96f6828](https://github.com/plasmonized/containerized-mioty-service-center/commit/96f68289b0d957bccbbc16009a381b437e60e27b))


### Bug Fixes

* address mypy issues from failing CI ([766511e](https://github.com/plasmonized/containerized-mioty-service-center/commit/766511eb4e0920d1f250c453a9a2379e533ed474))
* align docs artifact path with custom outDir in vitepress config ([b2b2b21](https://github.com/plasmonized/containerized-mioty-service-center/commit/b2b2b21ae868873c9745466ea1dbb137b2bd8b04))
* correct action versions and remove pip cache for uv-based jobs ([233af28](https://github.com/plasmonized/containerized-mioty-service-center/commit/233af28e5498ab3300186f4dc25a3eb5ca3252bb))
* correct branch references in config to use main instead of release ([ffa0fdd](https://github.com/plasmonized/containerized-mioty-service-center/commit/ffa0fddae34cc87cf96bac6d0c6a89546d4bb35c))
* entrypoint ([8b72eba](https://github.com/plasmonized/containerized-mioty-service-center/commit/8b72ebadeb87ae059923b3222d6c9da6fb5a022c))
* harden certificate file path handling in web ui ([9b4fdc2](https://github.com/plasmonized/containerized-mioty-service-center/commit/9b4fdc20fd56fec5163bdd270c93aae742865a71))
* normalize VERSION to semver format for Release Please compatibility ([ba7f9b1](https://github.com/plasmonized/containerized-mioty-service-center/commit/ba7f9b137617ce2b07ae87c97034479ebef60190))
* remove deprecated ruff rules (E128, E129, F824, W503, W504) not supported in ruff 0.15 ([60fe35e](https://github.com/plasmonized/containerized-mioty-service-center/commit/60fe35e9335133b50a23bb044821851c651c7e7a))
* replace type=semver with type=ref,event=tag for 2-part version tags ([334748e](https://github.com/plasmonized/containerized-mioty-service-center/commit/334748e8807d5e5cca31c653e23ba893ba785c8c))
* revert changes of different PR ([2de4d46](https://github.com/plasmonized/containerized-mioty-service-center/commit/2de4d4649a864e53040eba399a1df44cd4902573))
* revert changes of different PR ([7d2a068](https://github.com/plasmonized/containerized-mioty-service-center/commit/7d2a068a205af6fe50ed9674b58d3c6c0e5e3bdc))
* revert entrypoint sh ([33ef32d](https://github.com/plasmonized/containerized-mioty-service-center/commit/33ef32d4db463b28e67d40c2844ac3d952709809))
* run docker-pr on all feature branches ([1df3377](https://github.com/plasmonized/containerized-mioty-service-center/commit/1df337740daf1f310a2e5174583097029defa447))
* run docker-pr on push to PR branch ([154b140](https://github.com/plasmonized/containerized-mioty-service-center/commit/154b140d598a83f6c906cfa6018475f1db208fab))
* sanitize config update errors and log blocked cert path traversal ([9eb8d1d](https://github.com/plasmonized/containerized-mioty-service-center/commit/9eb8d1db1bb8a6956234c89700737d12e3a28838))
* satisfy ci ruff formatting and mypy checks ([98156d4](https://github.com/plasmonized/containerized-mioty-service-center/commit/98156d48a8849e0b21d4b654efd833c0ef1eac02))
* toLowerCase() removed ([4a2a3f9](https://github.com/plasmonized/containerized-mioty-service-center/commit/4a2a3f9d280b0e822caf58db9ef205349d6d691d))
* toLowerCase() removed ([5a855ac](https://github.com/plasmonized/containerized-mioty-service-center/commit/5a855acdea1a0c0f2b720ee617442e8fd5767e36))
* update manifest to semver format ([7fe4fa6](https://github.com/plasmonized/containerized-mioty-service-center/commit/7fe4fa64044cf1c4f0bb8141e9b557b1da70832a))
* update SENSOR_CONFIG_FILE in .env.example to config/endpoints.json ([2291bc3](https://github.com/plasmonized/containerized-mioty-service-center/commit/2291bc31711da53b696317b29659c7daa89309c0))
* use toLowerCase() for docker image tags ([ae407cb](https://github.com/plasmonized/containerized-mioty-service-center/commit/ae407cbb01da8544cf01829b604e6c1a1a7cfb70))
