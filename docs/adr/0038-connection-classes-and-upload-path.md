# ADR-0038: Connection Classes and the Upload Path

> **Status:** Proposed • **Date:** 2026-11-10

## 1. Context & Problem

Today the Cloud-Sync-Worker (v0.6.0) uploads every recording as FLAC to one rclone target. One bandwidth limit (`1M` by default) and an optional window of hours govern it. That suffices for a single station on a home connection, but not for what is planned:

*   **Stations connect in three ways.** Each way has its own cost and its own limit:
    *   **Ethernet**, with PoE where a cable reaches. On a fibre line there is room, but the upload is still shared with the household, and the household must never notice the station.
    *   **Wi-Fi**, which shares airtime with the household. A station with a weak signal takes more airtime per byte.
    *   **LTE**, where neither of the others reaches. It is billed by the megabyte.
*   **Raw data should be collected centrally** wherever the connection allows: for research, for re-analysis with better models, and as a backup.
*   **The volumes are large.** One microphone produces, on average (estimate, FLAC at about 55 % of PCM):

    | Stream | Mean rate | Per day | Per year |
    | --- | --- | --- | --- |
    | 48 kHz processed | ~0.43 Mbit/s | ~4.6 GB | ~1.7 TB |
    | 384 kHz raw | ~3.4 Mbit/s | ~37 GB | ~13 TB |

    A hundred 48 kHz microphones produce about 0.46 TB a day, or 170 TB a year, at a sustained 43 Mbit/s. A fleet VM can neither store that nor pass it through cheaply. A home NAS can hold it for a few stations, not for hundreds.
*   **The fleet server is defined for status, settings and results** ([ADR-0032](0032-api-first-station-contract.md)). Nothing yet decides where audio goes.

## 2. Decision

**We chose:** to separate *what* goes up from *how* it may go up.

*   A station sorts everything it uploads into five data tiers and sends them in tier order.
*   A connection class limits which tiers go up, how fast and how much. The station picks the class from the active network connection; the user can override it.
*   Audio goes directly from the station to an S3-compatible storage target. The fleet server carries metadata only.

### 2.1 Data tiers

| Tier | Content | Volume per station and day |
| --- | --- | --- |
| 0 Status | health summary, alerts, upload backlog | well under 1 MB |
| 1 Results | detections, hourly rollups ([ADR-0037](0037-sqlite-station-database.md)), index of held files | a few MB |
| 2 Evidence | detection clips | per 3 s clip: ~290 KB as WAV, ~12 KB as Opus at 32 kbit/s |
| 3 Processed audio | 48 kHz stream, FLAC | ~4.6 GB per microphone |
| 4 Raw audio | stream at native rate, e.g. 384 kHz, FLAC | up to ~37 GB per microphone |

A lower tier is always sent before a higher one. Within a tier:

*   Tiers 0–2 go newest first, because that is what people look at.
*   Tiers 3–4 go oldest first, so that audio is uploaded before the Janitor needs its space.

### 2.2 Connection classes

A class is a preset of four values:

| | `saver` | `balanced` | `full` |
| --- | --- | --- | --- |
| Default for | metered connections: LTE, phone hotspot | Wi-Fi | Ethernet |
| Highest tier | 2, with a few clips a day (the best per species) | 3 | 4 |
| Bandwidth limit | none; the monthly budget governs | 5 Mbit/s, and at most ~15 % of the current Wi-Fi link rate | 20 Mbit/s |
| Monthly budget | e.g. 500 MB; from 80 % only tiers 0–1, at 100 % only tier 0 | none | none |
| Report interval to the fleet | 15 min over one long-lived connection | 1 min | 1 min |

*   **How a class is chosen.** The station reads the active connection from the host's NetworkManager:
    *   A connection marked metered (`connection.metered` is `yes` or `guess-yes`) gets `saver`. NetworkManager guesses `yes` for mobile broadband.
    *   Otherwise Wi-Fi gets `balanced` and Ethernet gets `full`.
    *   If the station cannot read the state, it assumes `saver`.
*   **The user can adjust any part of it.**
    *   They can assign any class to a named connection, for example `balanced` for a slow DSL line on Ethernet.
    *   They can change each value. The bandwidth limit is the slider of [US-U04](../user_stories/cloud_sync.md#us-u04), and every class may carry a time window.
    *   A fleet sets the same values per station or per group.
    *   The Wi-Fi link-rate fraction, like every number in the table, is a starting value to be confirmed by measurement.
*   **The class is a ceiling, not an order.** A separate collection policy says which tiers the owner wants stored centrally, per station or per group. It is separate because at fleet scale the limit is storage, not the link. The station uploads up to the lower of the two:
    *   Data that is wanted but not yet sent waits on the station (Store & Forward, [ADR-0011](0011-audio-recording-strategy.md)).
    *   Data that is not wanted is released to the Janitor as if it were uploaded.
*   **Requests.** A user or the fleet can request a time range of a higher tier. The range is queued as wanted and goes up as soon as the class allows it. A request marked urgent goes up within the budget even on `saver`.
*   **The station says when it cannot keep up.** It compares what its wanted tiers produce with what its class lets it send. If the class cannot carry that volume on average, the station raises an alert instead of letting the backlog grow until the Janitor deletes unsent data. Two examples:
    *   A station with one 48 kHz and one 384 kHz microphone produces 3.8 Mbit/s. On `balanced` at 5 Mbit/s it keeps pace, but a three-day outage then takes about ten days to catch up.
    *   On `full` at 20 Mbit/s the same backlog takes about 17 hours. This is why raw audio is a `full` tier by default.

### 2.3 A quiet guest in someone else's network

*   **One transfer, one connection.** Parallel streams and concurrent multipart parts take more than a fair share at the bottleneck. The upload runs with `--transfers 1`, `--multi-thread-streams 1` and `--s3-upload-concurrency 1`.
*   **The limit applies to the upload direction.** On fibre the upload is often a fraction of the 1000 Mbit/s download.
*   **The router can give way automatically.** The installation guide tells the owner to put the station into the router's background priority class. On a FRITZ!Box the class is labelled *Hintergrundanwendungen*, a German label quoted as the interface shows it. The station's other traffic is small, so classing the whole device costs nothing.
*   **Deferred: a delay-based controller.** It would back off when the round-trip time to the target rises (LEDBAT, RFC 6817), so the station yields even without router support. It waits for measurements from real households.

### 2.4 Upload path

*   **Control plane: the fleet server.** It receives status, results and the index of uploaded files (path, tier, size, SHA-256, time range) in the representations of ADR-0032. It keeps them in its own database and decides collection policies and requests. It stores no audio.
*   **Data plane: the storage target.** Audio goes from the station straight to an S3-compatible target, for example:
    *   a NAS running an S3 server (Garage, MinIO), reachable in the tailnet;
    *   an object store (Hetzner Object Storage, Backblaze B2);
    *   for a station without a fleet, any rclone target, as today.
*   **Scoped credentials.** In a fleet, the server gives each station a credential that may only write below that station's own prefix: no listing, no reading, no deleting. The server can rotate and revoke it, so a stolen station can neither read nor destroy other stations' data.
*   **Bundles, not segments.** The unit of upload is one hour of one stream of one microphone: one FLAC file and a manifest. The manifest records:
    *   the segment boundaries;
    *   the sample rate;
    *   the SHA-256;
    *   the clock state (`clock_synced`).

    A gap, such as a restart or an unplugged microphone, ends a bundle early. Ten-second segments would mean 8,640 objects per stream and day, each with its own request and checksum; hourly bundles mean 24. The segments stay on the station as they are, and bundles are built for upload only.
*   **No relay through the fleet server.** A station that cannot reach its target keeps the data and retries. Passing audio through the VM would double its traffic and make it the bottleneck of the whole fleet.
*   **Watch for the Tailscale relay.** When two tailnet nodes cannot connect directly, Tailscale relays their traffic through a DERP server. A DERP server on the fleet VM would then carry audio after all. The station reports whether its path to the target is direct or relayed. A target with a public HTTPS endpoint avoids the case.

### 2.5 Metered connections

*   **Reports are batched over one long-lived connection.** A report every 10 s over a fresh TLS connection would cost about 40 MB a day in handshakes alone (estimate: ~5 KB each). One report every 15 minutes over a reused connection costs well under 1 MB.
*   **The budget counts what the interface sends and receives,** not what the application does, so the VPN and the operating system count too. The billing day is a setting.
*   **Updates wait** for an unmetered connection unless a fleet forces them.
*   **The VPN's own keep-alive traffic on LTE is measured** before a default budget is fixed.

## 3. Options Considered

*   **One bandwidth limit for every connection (as now):** Rejected. A value safe for LTE starves Ethernet, and one that suits Ethernet empties an LTE plan within hours.
*   **The connection type alone decides, with no classes to assign:** Rejected. A slow DSL line on Ethernet and a fast Wi-Fi on fibre are both common, so the type serves only as the default.
*   **Audio through the fleet server to the NAS:** Rejected. It doubles the VM's traffic and makes the VM the bottleneck (§2.4).
*   **Audio stored on the fleet VM:** Rejected. A VM's disk does not scale to hundreds of terabytes a year.
*   **Presigned upload URLs instead of scoped credentials:** Rejected for now. An hourly 384 kHz bundle is about 1.5 GB and needs a multipart upload with one URL per part, so the uploader would have to be rewritten. A scoped credential keeps rclone.
*   **Uploading every 10-second segment on its own (as now):** Rejected for fleets because of the object count (§2.4).
*   **Adaptive rate control now:** Deferred. A fixed limit plus the router's priority class covers the households known so far.

## 4. Consequences

*   **Positive:**
    *   One station logic serves a lone station and a fleet. Only who sets the classes and the target differs.
    *   A station on LTE stays within its data plan and still reports what it detects.
    *   The fleet server stays small: it handles metadata only, with no audio traffic and no audio storage.
    *   Raw data reaches central storage wherever the link allows, and the station reports when it cannot keep up.
*   **Negative:**
    *   The Cloud-Sync-Worker becomes a scheduler over tiers, classes and budgets instead of a loop over recordings.
    *   A rootless container must read the host's network state, from NetworkManager over the system D-Bus.
    *   The Janitor's rule "deletable when uploaded" becomes "deletable when uploaded or not wanted", per tier.
    *   Bundling delays an upload by up to an hour and adds an encoding step.
    *   The collection policy decides how much storage a fleet consumes. The station cannot make that decision, so it must be set deliberately.
*   **Open:**
    *   How a station proves its identity to the fleet server ([ADR-0034](0034-authentication-and-authorization.md) leaves this open).
    *   Default budgets and limits, after measurement.
    *   The fleet server's database and storage.
*   **On acceptance these documents change:**
    *   `docs/user_stories/cloud_sync.md`: classes, tiers, budget, the keep-up alert.
    *   `services/processor/README.md`: the Cloud-Sync-Worker.
    *   ADR-0011: retention per tier.
    *   [ADR-0033](0033-unified-naming-and-global-identifiers.md): the `sync` section holds classes instead of one `bandwidth_limit_bytes_per_s` and `window`.
    *   `docs/services/tailscale.md`.
    *   `VISION.md`: Deployment & Fleet Management.
