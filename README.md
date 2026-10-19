## Split-horizon views for octoDNS

[![CI](https://github.com/DonQuinleone/octodns-views/actions/workflows/main.yml/badge.svg?branch=master)](https://github.com/DonQuinleone/octodns-views/actions/workflows/main.yml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue)](https://github.com/DonQuinleone/octodns-views/blob/master/LICENSE)

An [octoDNS](https://github.com/octodns/octodns/) processor that gives a record a different answer per target, so one config can drive both the public and the internal side of a split-horizon zone.

octoDNS sends every target the same records. Without views, the inside answer for a name has to live in a second config with its own sources. This processor lets a record carry an override for a named view, and maps each view to the targets that serve it. An override can change the record's type, which covers the common case of a CNAME outside and an A record inside.

### Installation

#### Command line

```
pip install octodns-views
```

#### requirements.txt/setup.py

Pinning specific versions or SHAs is recommended to avoid unplanned upgrades. The release workflow updates these pins after each stable release.

##### Versions

```
octodns==1.22.0
octodns-views==0.1.0
```

##### SHAs

```
-e git+https://git@github.com/octodns/octodns.git@94bc80eb03f662565940dd2d4af5c20ccd61915e#egg=octodns
-e git+https://git@github.com/DonQuinleone/octodns-views.git@2eced80d69eac9cfe82b46d8ab3355f4ceb52131#egg=octodns_views
```

### Documentation

- [Quick reference](docs/quick-reference.md): config, override syntax, errors and limits on one page
- [Split-horizon DNS with Katapult and PowerDNS](docs/split-horizon-katapult-powerdns.md): a worked setup, from config to checking the answers

### Configuration

Map each view to the ids of the targets that serve it, and add the processor to the zones that use views:

```yaml
processors:
  views:
    class: octodns_views.Views
    views:
      inside: [internal-dns]

zones:
  example.com.:
    sources: [config]
    processors: [views]
    targets: [public-dns, internal-dns]
```

A target can be in only one view. Targets outside every view get the records as written.

Give a record an override for a view under `octodns.views`:

```yaml
app:
  octodns:
    views:
      inside:
        type: A
        value: 192.0.2.5
  type: CNAME
  value: edge.example.net.
www:
  octodns:
    views:
      inside:
        value: 192.0.2.1
  type: A
  value: 198.51.100.1
```

`public-dns` gets `app` as a CNAME and `www` as `198.51.100.1`. `internal-dns` gets `app` as an A record for `192.0.2.5`, and `www` as `192.0.2.1`.

An override is a record of its own, written as any other record:

- It replaces the record's values outright, rather than merging with them.
- `type` and `ttl` default to the record's own when the override leaves them out.
- It takes the record's `octodns` settings, without `views`, and can't set its own. A record that's `included` or `excluded` for a target stays that way whatever its override says.

Every target gets its records without the `views` data. That keeps a YAML target or `octodns-dump` free of the overrides for other views.

For a name that exists in only one view, use octoDNS's built-in `included` or `excluded` instead:

```yaml
dashboard:
  octodns:
    included: [internal-dns]
  type: A
  value: 192.0.2.7
```

#### Validation

When `octodns-sync` or `octodns-dump` processes the source zone, the processor applies each view to a copy of the zone. It then validates the result the same way octoDNS validates any zone. The plan fails before any target is touched if:

- an override names a view the processor config doesn't define;
- an override isn't a valid record of its type, or sets `octodns`;
- `octodns.views`, or an override in it, isn't a mapping;
- an override leaves the zone invalid. Examples are a CNAME beside other records, or a type that another record at the name already has.

For each target in a view, the target's own support checks run again over the overrides. With `strict_supports`, an override of a type or feature the target doesn't support fails the plan. Without it, the override is dropped with a warning.

`octodns-validate` doesn't run processors, so it checks none of this.

#### Limits

- Every target must support the record's own type, as well as any override type. octoDNS drops or rejects unsupported records before processors run, so a record of a type the view's target lacks never reaches its override. Give such a name one record per view with `included` instead.
- For a target in a view, the provider's desired-zone hook runs a second time over the overrides. That's safe for octoDNS's own checks, and a provider that overrides the hook needs to tolerate it.
- The processor can't see which targets exist. A misspelt target id in `views` puts that target in no view, and it gets the records as written.

### Contributing

Contributions are welcome as pull requests against `master`. Report security vulnerabilities privately, as [SECURITY.md](SECURITY.md) describes, rather than in an issue.

#### Development

```
./script/bootstrap
```

This creates a virtual environment in `env/`, installs the pinned runtime and development requirements, and installs a pre-commit hook that runs the same checks as CI. The [scripts](/script/) follow the [Scripts to Rule Them All](https://github.com/github/scripts-to-rule-them-all) pattern:

| Script | What it does |
| --- | --- |
| `./script/test` | Runs the tests |
| `./script/coverage` | Runs the tests with branch coverage; anything under 100% fails |
| `./script/lint` | Checks the code with pyflakes |
| `./script/format` | Formats the code with isort and black |
| `./script/cibuild` | Runs everything CI runs |

The tests run the processor against in-memory zones, and one test runs a full `octodns-sync` with YAML targets. Nothing reaches a real DNS provider.

Every pull request needs a changelog entry, which CI checks. Use `none` for changes that don't belong in the release notes:

```
./script/changelog create -t <none|patch|minor|major> "What changed, as a release note"
```

#### Releasing

Versions follow [SemVer](https://semver.org/), with pre-releases written `1.0.0-beta.1` and `1.0.0-rc.1`. The version lives in `octodns_views/__init__.py` and the tag is `v` plus that version. PyPI shows pre-releases in Python's spelling (`1.0.0rc1`), and `pip` installs them only when asked with `--pre`.

1. Bump the version and write the changelog from the pending entries:

   ```
   ./script/changelog bump --version 1.0.0-rc.1 --make-changes
   ```

2. Open a pull request with the result, and merge it once CI passes.
3. From an up-to-date `master`, run `./script/release`. It refuses a dirty tree or a `HEAD` that isn't `origin/master`, then signs and pushes the tag.

The tag starts the release workflow, which waits for approval on the `pypi` environment before publishing:

| Step | Pre-release | Stable |
| --- | :-: | :-: |
| Checks the tag is on `master` and matches the version, then lints, tests and builds | ✅ | ✅ |
| Publishes to PyPI through trusted publishing | ✅ | ✅ |
| Creates a GitHub release with the changelog section and built files | ✅ | ✅ |
| Opens a pull request updating the pins under [Installation](#installation) | ❌ | ✅ |

Workflow-opened pull requests don't start CI on their own; close and reopen them to run the checks.

