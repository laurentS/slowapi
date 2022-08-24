# Change Log

## [0.1.6] - 2022-08-20

### Added
- Added feature to support providing functions for dynamically defined limits (thanks @maratsarbasov)
- Added github action to check for unused imports (thanks @twcurrie)
- Added coverage report in CI (thanks @karlnewell)
- Added Python 3.10 to CI (thanks @Reuben Thomas-Davis)

### Changed
- Shifted redis to extras, removed test imports of library (thanks @ME-ON1)
- Upgraded dependencies (thanks @dependabot, @Rested, @laurents)
- Updated documentation and example code (thanks @Dustyposa, @laurents, @nootr)
- Set minimum Python version to 3.6.2 (thanks @Rested)

### Fixed
- Fixed exempt decorator for async routes (thanks @laurents)
- Handled newly raised exception from parsing library (thanks @Rested)

## [0.1.5] - 2021-08-28

### Changed

- Switched to poetry-core for building #54 (thanks @fabaff)
- Improved the docs
- Upgraded a few dependencies (thanks @dependabot)

### Fixed

- Resolved bug of unregistered endpoints in the disabled state #46 (thanks @twcurrie)
- Fixed bug with Retry-After headers #60 (thanks again @twcurrie)


## [0.1.4] - 2021-02-21

- Made the enabled option actually useful (thanks @kodekracker for the report) #35
- Fixed 2 bugs in middleware #30 and #37 (thanks @xuxygo for the PR, and @papapumpnz for the report)
- Fixed errors in docs
- Bump lxml to 4.6.2 (dependabot - only used for doc generation)

## [0.1.3] - 2020-12-24

### Added

- Added some setup examples in documentation

### Fixed

- Routes returning a dict don't error when turning on headers (#18), thanks to @glinmac
- Fix CI crash following github actions changes in env settings

## [0.1.2] - 2020-10-01

### Added

- Added support for default limits and exempt routes, thanks to @Rested
- Added documentation
- Added more tests, thanks to @thomasleveil
- Fix documentation bug, thanks to @brumar
- Added CI checks for formatting, typing and tests

### Changed

- Upgraded supported version of Starlette (0.13.6) and FastApi (0.61.1)

## [0.1.1] - 2020-03-11

### Added

- Added explicit support for typing

### Changed

- Upgraded supported version of Starlette (0.13.2) and FastApi (0.52.0)

## [0.1.0] - 2020-02-21

Initial release
