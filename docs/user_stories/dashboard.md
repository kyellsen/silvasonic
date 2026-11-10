# User Stories — Dashboard

> **Service:** Web-Interface (dashboard) · **Tier:** 1
>
> **Status:** TO-BE. The dashboard these stories describe is a single-page application on the [Station API](../api/index.md) ([ADR-0036](../adr/0036-svelte-spa-frontend.md), *Proposed*).

**Who:** one person with one station — in a garden, at a forest edge — who wants to know what lives there. They open the dashboard on a phone or a laptop, in the home network or over a VPN. They do not use a terminal and have no fleet.

**What every story assumes:**

- Every view is built from the Station API and from nothing else.
- Everything works on a phone held upright.
- Everything works without internet access; pictures and texts of species come from the station.
- Nothing a user does in the dashboard interrupts recording, unless the action says so before it is confirmed.
- All interface text exists in English and German; times are shown in the station's time zone.

Signing in, live updates and hiding disabled modules are cross-cutting behaviour, described in [Web-Interface stories](web_interface.md) (US-WI01 to US-WI03). The module stories for [live listening](icecast.md), [bats](batdetect.md) and weather build on the stories here.

---

## Must have

<a id="us-d01"></a>
## US-D01: Set up a new station 🚀

> **As a user**
> **I want to** take a new station into operation from my phone,
> **so that** it records correctly placed and under my control within a few minutes.

### Acceptance Criteria

- [ ] A station that has never been set up shows the setup page and nothing else.
- [ ] Setup asks for the station's setup code, a username and a password. No account exists before.
- [ ] I give the station a name, pick its position on a map or enter coordinates, and confirm time zone and language; time zone and language are preset from my browser.
- [ ] After setup I am signed in and see whether a microphone is connected and recording.
- [ ] Without a position the station works; the dashboard says that species are not filtered by region until one is set.

### References

- [ADR-0034: Authentication and Authorization](../adr/0034-authentication-and-authorization.md)
- Contract: `getInfo`, `completeSetup`, `updateStation`

---

<a id="us-d02"></a>
## US-D02: See at a glance that everything runs ✅

> **As a user**
> **I want to** see on one page whether my station is recording and healthy,
> **so that** I notice a problem the day it starts, not when I look for last week's recordings.

### Acceptance Criteria

- [ ] One overall state — fine, needs attention, not recording — is the first thing I see.
- [ ] Per microphone: recording or not, and when the last segment was written.
- [ ] Storage: how full, and for how many days the space lasts at the current rate.
- [ ] Whether the station clock is synchronised; if not, a notice that timestamps may be off.
- [ ] How many recordings wait for analysis.
- [ ] Open alerts, the most severe first, each saying what is wrong in a sentence.
- [ ] Processor load, memory and temperature are visible, below the above.
- [ ] The page updates by itself; a lost connection is shown and recovers without a reload.

### References

- [US-WI02: Real-time status without reloading](web_interface.md#us-wi02)
- [US-C05](controller.md#us-c05), [US-P04](processor.md#us-p04), [US-B05](birdnet.md#us-b05)
- Contract: `getStationStatus`, `listAlerts`, `streamEvents`

---

<a id="us-d03"></a>
## US-D03: See what was heard 🐦

> **As a user**
> **I want to** see which species my station detected today and recently,
> **so that** I know what lives around it.

### Acceptance Criteria

- [ ] Species are shown with picture, name in my language, number of detections and time last heard.
- [ ] I switch between today, the last 7 days and all time.
- [ ] A species detected for the first time ever is marked as new.
- [ ] I sort by last heard, by number of detections or by name, and search by name.
- [ ] Sound classes that are not species, such as speech or engines, are kept apart from the species.
- [ ] Detections I rejected do not count.

### References

- [US-B02](birdnet.md#us-b02)
- Contract: `listSpecies`, `getStatsSummary`, `getSpeciesImage`

---

<a id="us-d04"></a>
## US-D04: Listen to a detection and judge it 🎧

> **As a user**
> **I want to** hear and see what the station took for a species,
> **so that** I can decide whether I believe it.

### Acceptance Criteria

- [ ] A list of detections, newest first, with species, time, confidence and microphone.
- [ ] I filter by period, species, minimum confidence and microphone.
- [ ] I play the clip of a detection in the list, without leaving it.
- [ ] Opening a detection shows a spectrogram of the clip with the detected span marked.
- [ ] From a detection I reach the whole recording and hear what came before and after.
- [ ] A detection whose audio has been deleted says so; it does not show a broken player.
- [ ] A detection from a recording made with an unsynchronised clock is marked.

### References

- [US-B01](birdnet.md#us-b01)
- Contract: `listDetections`, `getDetection`, `getDetectionClip`, `getRecording`, `getRecordingAudio`

---

<a id="us-d05"></a>
## US-D05: Get to know a species 📖

> **As a user**
> **I want to** open a page about one species,
> **so that** I learn what it is and when it visits.

### Acceptance Criteria

- [ ] Picture with its author and licence, names in my language and the scientific name, a short description, conservation status.
- [ ] When I first and last heard it, how often, and the highest confidence.
- [ ] At which hours of the day it is heard.
- [ ] Its best detections, to listen to.
- [ ] A link to read more, which is the only thing on the page that needs internet access.

### References

- Contract: `getSpecies`, `getDetectionHeatmap`, `listDetections`

---

<a id="us-d06"></a>
## US-D06: Manage my microphones 🎙️

> **As a user**
> **I want to** see and control every microphone on the station,
> **so that** I decide what is recorded and how.

### Acceptance Criteria

- [ ] Each microphone shows whether it is connected, whether it records, its profile and its sample rate.
- [ ] I give a microphone a name of my own, such as "pond".
- [ ] I switch a microphone off and on; off stops its recording at once.
- [ ] A newly connected microphone the station did not recognise for certain waits for me to assign a profile or to ignore it.
- [ ] I change the profile of a microphone; the dashboard says beforehand that its recording restarts.
- [ ] A microphone that failed and recovered shows how often; one that gave up says why.

### References

- [US-C01](controller.md#us-c01), [US-C03](controller.md#us-c03), [US-C06](controller.md#us-c06), [US-C07](controller.md#us-c07), [US-C10](controller.md#us-c10), [US-R06](recorder.md#us-r06)
- Contract: `listMicrophones`, `updateMicrophone`, `listMicrophoneProfiles`

---

<a id="us-d07"></a>
## US-D07: Keep storage under control 💾

> **As a user**
> **I want to** understand what fills the disk and what the station deletes,
> **so that** nothing I care about disappears unnoticed.

### Acceptance Criteria

- [ ] How much space recordings, clips and everything else take.
- [ ] The current retention level and what it means, in a sentence.
- [ ] A forecast: at the current rate, in how many days deletion starts.
- [ ] A log of deleted recordings with time and reason.
- [ ] I change the thresholds at which the station starts deleting; a combination that makes no sense is refused with an explanation.
- [ ] I delete a single recording by hand, with its clips and detections, after a confirmation.

### References

- [US-P02](processor.md#us-p02), [US-P03](processor.md#us-p03)
- Contract: `getStorage`, `listRecordings`, `deleteRecording`, `updateSettingsSection`

---

<a id="us-d08"></a>
## US-D08: Tune detection ⚙️

> **As a user**
> **I want to** switch analysis on or off and adjust how strict it is,
> **so that** I get fewer false detections or miss fewer real ones.

### Acceptance Criteria

- [ ] I switch bird detection on and off and see whether it runs and how far behind it is.
- [ ] I set the minimum confidence and the sensitivity, each with a sentence on what it changes.
- [ ] I restrict detections to species plausible at my location and season, or lift that.
- [ ] A change applies to recordings analysed from then on; the dashboard says so.
- [ ] Modules my station cannot run are shown as unavailable, not hidden.

### References

- [US-B04](birdnet.md#us-b04), [US-B06](birdnet.md#us-b06), [US-WI03](web_interface.md#us-wi03)
- Contract: `listModules`, `updateModule`, `getSettingsSection`, `updateSettingsSection`

---

## Should have

<a id="us-d09"></a>
## US-D09: See patterns over time 📊

> **As a user**
> **I want** charts of activity over days and seasons,
> **so that** I see when my garden is busy and how it changes.

### Acceptance Criteria

- [ ] Detections and number of species per day, week or month.
- [ ] Activity by hour of day and date, for all species or one.
- [ ] The most detected species of a period.
- [ ] How much of each day was recorded, so that a quiet day can be told from a day the station was off.

### References

- Contract: `getDetectionTimeline`, `getDetectionHeatmap`, `getRecordingCoverage`, `listSpecies`

---

<a id="us-d10"></a>
## US-D10: Take my data with me 📤

> **As a user**
> **I want to** download my detections and recordings,
> **so that** I can use them elsewhere or report them.

### Acceptance Criteria

- [ ] I download the detections I filtered as a CSV file, with names in my language.
- [ ] I download the clip of a detection and the audio of a recording.
- [ ] The file names say station, date and species where they apply.

### References

- Contract: `exportDetections`, `getDetectionClip`, `getRecordingAudio`

---

<a id="us-d11"></a>
## US-D11: Back up recordings to my own storage ☁️

> **As a user**
> **I want to** have recordings copied to a storage of mine,
> **so that** they survive a failed disk and I can keep more than the station holds.

### Acceptance Criteria

- [ ] I enter a target, test the connection and get a clear answer before I save.
- [ ] A saved password is never shown again.
- [ ] I see whether uploading runs, how much waits, and when it last succeeded.
- [ ] I see failed uploads with their cause.
- [ ] I limit the bandwidth and the hours of the day uploads may use.

### References

- [Cloud Sync stories](cloud_sync.md)
- Contract: `getSyncStatus`, `replaceSyncTarget`, `testSyncTarget`, `listUploads`, `updateModule`

---

<a id="us-d12"></a>
## US-D12: Find out what went wrong 🔍

> **As a user**
> **I want to** look into what the station has been doing,
> **so that** I can fix a problem myself or describe it to someone who can.

### Acceptance Criteria

- [ ] A history of what happened: microphone connected, recording restarted, storage level changed, setting changed.
- [ ] Live log output, filtered by component and severity, that I can pause.
- [ ] An alert leads to the place where I can act on it.

### References

- [US-C09](controller.md#us-c09)
- Contract: `listEvents`, `streamLogs`, `listAlerts`

---

<a id="us-d13"></a>
## US-D13: Be told when something matters 🔔

> **As a user**
> **I want to** be notified about problems and special visitors,
> **so that** I do not have to keep looking.

### Acceptance Criteria

- [ ] I mark species I want to hear about.
- [ ] I am notified when a marked species or a species new to my station is detected.
- [ ] I am notified when the station stops recording or the disk runs full.
- [ ] I choose how severe a problem must be, and acknowledge an alert to silence it.

### References

- Contract: `updateSpecies`, `listAlerts`, `acknowledgeAlert`, `updateSettingsSection` (`notifications`)

---

<a id="us-d14"></a>
## US-D14: Correct the station 🖊️

> **As a user**
> **I want to** confirm or reject a detection,
> **so that** my lists and statistics show what was really there.

### Acceptance Criteria

- [ ] I confirm or reject a detection with one tap while listening to it.
- [ ] I state what it really was, and add a note.
- [ ] Rejected detections leave my species lists and statistics; I can still find them.
- [ ] I filter detections by whether I have reviewed them.

### References

- Contract: `reviewDetection`, `listDetections`

---

<a id="us-d15"></a>
## US-D15: Use the dashboard as an app 📱

> **As a user**
> **I want to** install the dashboard on my phone,
> **so that** it opens like an app, at home and on the road.

### Acceptance Criteria

- [ ] I add the dashboard to the home screen of an iPhone or Android phone; it opens without browser controls.
- [ ] It starts without waiting for the network and then loads current data.
- [ ] It works wherever I reach the station under an address with a trusted certificate; on any other address the dashboard tells me which address to use.
- [ ] Without a connection to the station it says so and shows nothing stale as current.

### References

- [ADR-0035: HTTPS and Certificates](../adr/0035-https-and-certificates.md), [ADR-0036](../adr/0036-svelte-spa-frontend.md)
- Contract: `getInfo` (`trusted_origins`), `getNetwork`

---

<a id="us-d16"></a>
## US-D16: Share the station without sharing control 👥

> **As a user**
> **I want to** let others look at my station,
> **so that** family or a project partner can follow along without being able to change it.

### Acceptance Criteria

- [ ] I create accounts that may only look and listen, accounts that may also operate, and further administrators.
- [ ] I see where I am signed in and sign a device out.
- [ ] I create an access token for another program, limited to what it needs, and revoke it.
- [ ] I see who changed what.

### References

- [ADR-0034: Authentication and Authorization](../adr/0034-authentication-and-authorization.md)
- Contract: `createUser`, `listSessions`, `revokeSession`, `createApiToken`, `listAuditLog`
