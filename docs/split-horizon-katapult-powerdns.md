# Split-horizon DNS with Katapult and PowerDNS

This guide sets up one octoDNS config that serves `example.com` two ways:

- **Outside**, from [Katapult](https://github.com/DonQuinleone/octodns-katapult). Public resolvers get the public answers.
- **Inside**, from an internal [PowerDNS](https://github.com/octodns/octodns-powerdns) authoritative server. Clients on your network get internal addresses for the same names, and a few names that exist only inside.

```
                         ┌────────────┐
public resolvers ───────▶│  Katapult  │  app.example.com  CNAME edge.example.net.
                         └────────────┘
                               ▲
              octodns-sync ────┤ one config, one zone file
                               ▼
                         ┌────────────┐
internal resolver ──────▶│  PowerDNS  │  app.example.com  A 192.0.2.10
                         └────────────┘
```

The files below are in [`docs/examples/split-horizon`](examples/split-horizon). CI syncs them against stand-ins with Katapult's and PowerDNS's own supported record types, so they work as written.

## Before you start

You need:

- A Katapult API token with the `Core: Manage DNS zones/records` scope, and your organisation's sub-domain. The [octodns-katapult README](https://github.com/DonQuinleone/octodns-katapult#configuration) shows where to find both.
- `example.com` added to Katapult, and verified there by delegation or its TXT record. If octoDNS manages the apex TXT records, include Katapult's verification record in the zone file, or the first sync deletes it.
- A PowerDNS authoritative server with its HTTP API turned on, and `example.com` created on it. In `pdns.conf`, the API settings are:

  ```
  api=yes
  api-key=<a long random key>
  webserver=yes
  webserver-address=192.0.2.53
  webserver-port=8081
  webserver-allow-from=<the address octoDNS runs from>
  ```

Install the pieces, pinned:

```
octodns==1.22.0
octodns-katapult==1.0.0
octodns-powerdns==1.2.0
octodns-views==0.1.0
```

## The config

```yaml
---
providers:
  config:
    class: octodns.provider.yaml.YamlProvider
    directory: ./zones
    default_ttl: 3600
    enforce_order: true
    escaped_semicolons: false
  katapult:
    class: octodns_katapult.KatapultProvider
    token: env/KATAPULT_API_TOKEN
    organization: env/KATAPULT_ORG
  powerdns:
    class: octodns_powerdns.PowerDnsProvider
    host: 192.0.2.53
    port: 8081
    api_key: env/POWERDNS_API_KEY

processors:
  views:
    class: octodns_views.Views
    views:
      inside: [powerdns]

zones:
  example.com.:
    sources: [config]
    processors: [views]
    targets: [katapult, powerdns]
```

- `config` reads the zone file from `./zones`, relative to where you run `octodns-sync`.
- Katapult and PowerDNS read their secrets from the environment: `KATAPULT_API_TOKEN`, `KATAPULT_ORG` and `POWERDNS_API_KEY`.
- The `views` processor puts the `powerdns` target in a view called `inside`. Katapult is in no view, so it gets every record as written.
- `processors: [views]` turns the processor on for this zone.

## The zone file

`zones/example.com.yaml`:

```yaml
---
'':
  octodns:
    views:
      inside:
        type: A
        value: 192.0.2.10
  type: ALIAS
  value: edge.example.net.
app:
  octodns:
    views:
      inside:
        ttl: 300
        type: A
        value: 192.0.2.10
  type: CNAME
  value: edge.example.net.
mail:
  type: A
  value: 203.0.113.25
nas:
  octodns:
    included: [powerdns]
  type: A
  value: 192.0.2.20
status:
  octodns:
    excluded: [powerdns]
  type: CNAME
  value: status.example.org.
www:
  type: CNAME
  value: example.com.
```

Keys are sorted inside each record as well as between records, because YamlProvider enforces the order by default.

Here's what each side serves:

| Name | Katapult (outside) | PowerDNS (inside) | How |
|---|---|---|---|
| `example.com` | ALIAS `edge.example.net.` | A `192.0.2.10` | Override changes the type |
| `app` | CNAME `edge.example.net.` | A `192.0.2.10`, TTL 300 | Override changes the type and TTL |
| `mail` | A `203.0.113.25` | A `203.0.113.25` | No override |
| `nas` | Nothing | A `192.0.2.20` | `included: [powerdns]` |
| `status` | CNAME `status.example.org.` | Nothing | `excluded: [powerdns]` |
| `www` | CNAME `example.com.` | CNAME `example.com.` | No override; it follows the apex on each side |

`www` needs no override: it points at the apex, and each side answers for the apex its own way.

## Plan, then apply

Run from the directory holding `config.yaml`:

```
export KATAPULT_API_TOKEN=... KATAPULT_ORG=... POWERDNS_API_KEY=...
octodns-sync --config-file config.yaml
```

Without `--doit` this only plans. Check that the plan for `katapult` has the outside answers and the plan for `powerdns` has the inside ones, then apply:

```
octodns-sync --config-file config.yaml --doit
```

A broken override fails the plan before either provider is touched. The [quick reference](quick-reference.md#errors) lists the errors.

## Send internal clients to PowerDNS

PowerDNS authoritative answers only for its own zones. Your network's resolver needs to forward `example.com` to it, and resolve everything else as usual. With the PowerDNS Recursor, that's one setting in the older `recursor.conf` style:

```
forward-zones=example.com=192.0.2.53
```

Newer Recursor versions also take a YAML config. See the Recursor documentation for the same setting there. Most other resolvers call this a conditional forwarder or a stub zone.

## Check it

Ask each side directly:

```
dig +short app.example.com @<a Katapult nameserver>
dig +short app.example.com @192.0.2.53
```

The first answer is `edge.example.net.` followed by its addresses, and the second is `192.0.2.10`. A client on your network asking its usual resolver should get `192.0.2.10` too.

## Things to watch

- **Both providers must support each record's own type.** octoDNS drops records a target can't serve before processors run. Both support ALIAS, which is why the apex example works. A type only one side supports needs one record per side with `included` and `excluded`.
- **ALIAS on PowerDNS.** Here the inside apex is overridden to an A record, so PowerDNS never serves the ALIAS. If you leave an ALIAS in place for PowerDNS, it resolves it only with `expand-alias=yes` and a `resolver=` set in `pdns.conf`.
- **TTLs.** Katapult's minimum TTL is 60.
- **Apex NS records.** Both providers support managing them. Leave NS out of the zone file unless you mean octoDNS to manage them, and give PowerDNS an override if the inside nameservers differ.
- **`octodns-validate` doesn't run processors.** Use a planning run of `octodns-sync` to check overrides.
