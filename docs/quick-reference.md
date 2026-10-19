# Quick reference

octodns-views gives a record a different answer per target. For the full walk-through, see [Split-horizon DNS with Katapult and PowerDNS](split-horizon-katapult-powerdns.md).

## Processor config

```yaml
processors:
  views:
    class: octodns_views.Views
    views:
      inside: [internal-dns]
      lab: [lab-dns]
```

| Key | Value |
|---|---|
| `class` | `octodns_views.Views` |
| `views` | A map from each view name to a list of target ids. A target can be in only one view. |
| `lenient` | Optional, `false` by default. Relaxes record validation of overrides, as octoDNS's own `lenient` does. |

Add the processor to each zone that uses views:

```yaml
zones:
  example.com.:
    sources: [config]
    processors: [views]
    targets: [public-dns, internal-dns]
```

## Record overrides

Overrides go under `octodns.views`, one per view. The examples below keep the keys sorted, which YamlProvider requires by default (`enforce_order`).

### Same type, different value

```yaml
www:
  octodns:
    views:
      inside:
        value: 192.0.2.1
  type: A
  value: 198.51.100.1
```

### Different type

```yaml
app:
  octodns:
    views:
      inside:
        type: A
        value: 192.0.2.5
  type: CNAME
  value: edge.example.net.
```

### Different TTL

```yaml
api:
  octodns:
    views:
      inside:
        ttl: 60
        value: 192.0.2.6
  type: A
  value: 198.51.100.6
```

### Several values

```yaml
pool:
  octodns:
    views:
      inside:
        values:
          - 192.0.2.7
          - 192.0.2.8
  type: A
  values:
    - 198.51.100.7
    - 198.51.100.8
```

### A name on one side only

These need no processor, because octoDNS's own `included` and `excluded` handle them:

```yaml
nas:
  octodns:
    included: [internal-dns]
  type: A
  value: 192.0.2.20
status:
  octodns:
    excluded: [internal-dns]
  type: CNAME
  value: status.example.org.
```

## What an override takes from its record

| Field | When the override leaves it out | When the override sets it |
|---|---|---|
| `type` | The record's type | Replaces it |
| `ttl` | The record's TTL | Replaces it |
| `value` / `values` | Nothing. An override must give its own. | Replaces them outright, with no merging |
| `octodns` | The record's settings, without `views` | Not allowed |

## What each target gets

Using the examples above, with `internal-dns` in the view `inside` and `public-dns` outside every view:

| Record | `public-dns` | `internal-dns` |
|---|---|---|
| `www`, same-type override | A `198.51.100.1` | A `192.0.2.1` |
| `app`, type change | CNAME `edge.example.net.` | A `192.0.2.5` |
| `nas`, `included: [internal-dns]` | Nothing | A `192.0.2.20` |
| `status`, `excluded: [internal-dns]` | CNAME `status.example.org.` | Nothing |

A record without an override goes to every target as written. A target in a view gets the record as written when there's no override for its view. No target receives the `views` data itself.

## Errors

| Error | Cause | Fix |
|---|---|---|
| `override for unknown view` | A record names a view the processor config doesn't define | Add the view to `views`, or correct the name |
| `invalid view override` | The override isn't a valid record of its type | Fix the value, or set `type` |
| `a view override cannot set octodns` | The override has its own `octodns` | Put the settings on the record |
| `leaves the zone invalid` | Applying a view breaks a zone rule, such as a CNAME beside other records | Override the other records too, or change the type |
| `Duplicate record` | The override's type is already used at that name | Override that record instead |
| `is in views ... and ...` | One target is listed under two views | List each target once |
| `SupportsException` | With `strict_supports`, the view's target doesn't support the override's type or features | Pick a type the target supports |

`octodns-validate` doesn't run processors. These checks run during `octodns-sync` and `octodns-dump`.

## Limits

- Every target must support the record's own type. octoDNS removes unsupported records before processors run, so the override never applies. Use one record per side with `included` instead.
- A target id that's misspelt in `views` can't be detected. That target is in no view, and it gets the records as written.
