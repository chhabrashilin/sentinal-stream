# Sentinel-Stream Inference Guide

> How to read every sensor value, endpoint, and alert — and what to do with the information.

This guide is for anyone consuming data from Sentinel-Stream: **lake managers**, **recreational users**, **researchers**, and **automated alert systems**. Each section explains what a metric means physically, what values are normal vs. alarming, and what action to take.

---

## Table of Contents

1. [The Four Core Sensors](#1-the-four-core-sensors)
2. [Thermal Stratification](#2-thermal-stratification)
3. [The Digital Twin (Physics-Informed ML)](#3-the-digital-twin-physics-informed-ml)
4. [48-Hour Foresight Risk Scores](#4-48-hour-foresight-risk-scores)
5. [Vessel & Recreation Guide](#5-vessel--recreation-guide)
6. [Data Quality Flags](#6-data-quality-flags)
7. [Ice-In Estimation Mode](#7-ice-in-estimation-mode)
8. [Node Swarm](#8-node-swarm)
9. [Decision Trees by User Type](#9-decision-trees-by-user-type)
10. [Compound Condition Analysis](#10-compound-condition-analysis)
11. [Seasonal Calendar](#11-seasonal-calendar)
12. [Alert Response Protocols](#12-alert-response-protocols)

---

## 1. The Four Core Sensors

### Air Temperature (`air_temp_c`)

**What it is:** Dry-bulb air temperature measured at buoy mast height (~2 m above water surface), in °C.

**Normal range for Lake Mendota:**

| Season       | Typical Range | Notes                                   |
|--------------|---------------|-----------------------------------------|
| Jan–Feb      | −15 to 0 °C   | Hard winter, ice likely                  |
| Mar–Apr      | 0 to 12 °C    | Ice-out period, spring onset            |
| May–Jun      | 10 to 22 °C   | Stratification establishing             |
| Jul–Aug      | 20 to 32 °C   | Peak summer                             |
| Sep–Oct      | 8 to 20 °C    | Cooling, fall overturn risk begins      |
| Nov–Dec      | −5 to 8 °C    | Pre-freeze, sensors retract             |

**What it tells you:**
- Air temperature drives surface heat flux — the rate at which the lake gains or loses heat.
- A sudden drop of 3–5 °C in air temperature overnight is a reliable precursor to fall overturn.
- Prolonged warm air > 25 °C accelerates surface warming, promoting HAB conditions.

**Action thresholds:**
- `< 0 °C sustained` → ice formation possible within 1–3 days; prepare sensors for winter mode
- `> 28 °C for 3+ days` → HAB risk elevated; increase chlorophyll monitoring frequency

---

### Wind Speed (`wind_speed_ms` / `smoothed_wind_ms`)

**What it is:** Cup anemometer reading at buoy mast height. Two values are available:
- `raw_wind_speed_ms` — instantaneous reading, includes 1 Hz turbulence noise
- `smoothed_wind_ms` — 10-reading (≈ 10 s) rolling mean; use this for all operational decisions

**Normal range:** 0–12 m/s on Lake Mendota. Values above 15 m/s are significant weather events.

**What it tells you:**

| Wind (m/s) | Beaufort | Lake Mendota Conditions                                |
|------------|----------|--------------------------------------------------------|
| 0–1        | 0–1      | Calm, mirror flat. Algae surface scum may form.        |
| 1–4        | 2–3      | Light ripples to small wavelets. Ideal paddling.       |
| 4–8        | 3–4      | Whitecaps common. SUP/canoe caution zone.              |
| 8–12       | 4–5      | Sustained chop. Rowing shells should dock.             |
| 12–18      | 5–7      | Rough for small craft. Sailing race postponement.      |
| > 18       | 7+       | Dangerous. All small craft should clear the lake.      |

**Ecological role:**
- Wind is the primary mixing driver. Above ~5 m/s, the epilimnion mixes, which disrupts HAB-forming cyanobacteria that prefer stagnant layers.
- Extended calm (< 2 m/s for 3+ days) combined with warm air is the classic HAB setup.
- A sudden wind event above 12 m/s on a stratified lake can trigger turnover within 24–48 hours.

---

### Surface Water Temperature (`water_temp_profile["0m"]`)

**What it is:** Thermistor measurement at 0 m depth (epilimnion surface layer), in °C.

**Normal range:**

| Season   | Surface (0m) | Deep (20m) | Δt (stratification) |
|----------|-------------|------------|---------------------|
| Post ice-out (Mar) | 3–6 °C | 3–4 °C | ~0.5 °C (mixed) |
| Late spring (May) | 12–16 °C | 6–10 °C | ~5–8 °C (weak strat.) |
| Summer peak (Jul) | 22–26 °C | 7–9 °C | ~15–18 °C (stratified) |
| Fall overturn (Oct) | 10–14 °C | 9–12 °C | ~1–3 °C (mixed) |
| Pre-freeze (Dec) | 1–3 °C | 3–4 °C | < 0 (inverse strat.) |

**What it tells you for recreation:**
- The surface temperature is what you feel when you enter the water.
- Below 10 °C: cold shock risk on immersion (involuntary gasping). Always wear a PFD.
- Below 5 °C: survival time without protection is under 30 minutes. Drysuit mandatory.
- Above 20 °C: comfortable for most activities. Cyanobacteria thrive in this range.

**What it tells you for ecology:**
- Rapid surface cooling (> 0.5 °C/hour) signals an impending mixing event.
- Surface warming above 24 °C + calm wind = highest HAB risk window.

---

### Chlorophyll-a (`chlorophyll_ugl`)

**What it is:** Fluorometric measurement of chlorophyll-a concentration, a proxy for algal biomass (µg/L = micrograms per litre).

**Visual appearance guide:**

| Chl-a (µg/L) | Appearance                                | Secchi Depth | Status     |
|--------------|-------------------------------------------|--------------|------------|
| < 5          | Crystal clear, blue-green tint            | > 4 m        | Excellent  |
| 5–15         | Slight green tinge, natural appearance    | 2–4 m        | Good       |
| 15–30        | Noticeably green, possible shore foam     | 1–2 m        | Fair       |
| 30–70        | Paint-like green, surface scum forming    | < 1 m        | HAB Advisory |
| > 70         | Bright blue-green or olive paint, scum    | < 0.5 m      | HAB Warning |

**Health implications:**
- Cyanobacterial HABs produce microcystin (liver toxin) and cylindrospermopsin.
- At > 30 µg/L: avoid skin contact, especially children and pets.
- At > 70 µg/L: do not enter the water. Avoid inhaling aerosols (mowing near shore, jet skiing).
- After a bloom collapses (chl drops rapidly), toxin levels may remain elevated for 1–2 weeks.

**Historical context for Mendota:**
- Lake Mendota is hypereutrophic — chl-a regularly exceeds 50–100 µg/L in summer.
- NTL-LTER records: mean summer chl-a ~35–60 µg/L. Peak events have exceeded 300 µg/L.
- The 2019–2020 phosphorus reduction efforts (cow manure management in the watershed) reduced peak chl-a by ~25%.

---

## 2. Thermal Stratification

**Endpoint:** `GET /stratification`

**What it is:** The degree to which the water column is thermally layered, computed as:

```
Δt = water_temp_0m − water_temp_20m
```

**Three states:**

| Status             | Δt        | Physical Meaning                                                  | Ecological Implications                              |
|--------------------|-----------|-------------------------------------------------------------------|------------------------------------------------------|
| `mixed`            | < 4 °C    | Full water-column circulation. Near-uniform temperature.          | O₂ uniform. Nutrients mixed. HAB risk low.           |
| `weakly_stratified`| 4–10 °C   | Thermocline forming. Surface warming faster than deep.            | O₂ starts depleting at depth. HAB risk building.    |
| `stratified`       | ≥ 10 °C   | Strong thermocline. Epilimnion thermally isolated from hypolimnion.| Deep O₂ depleting. HAB risk high. Turnover dangerous.|

**For lake managers:**
- `mixed` in spring: safe window for algaecide application (mixing distributes treatment).
- `weakly_stratified` in early summer: monitor phosphorus and algal growth daily.
- `stratified` in July–August: high alert for HAB and anoxia. Do not allow WWTP bypass events.
- `stratified` followed by rapid `mixed` in September: turnover event is occurring or imminent.

**For researchers:**
- Stratification drives the redox chemistry at the sediment-water interface.
- When hypolimnion goes anoxic (usually at `stratified` + Δt > 12 °C), internal phosphorus loading from sediments begins — a positive feedback loop for HABs.

---

## 3. The Digital Twin (Physics-Informed ML)

**Endpoint:** `GET /digital-twin`

**What it is:** A Ridge regression model trained on recent sensor data that predicts the full water-column temperature profile (0m, 5m, 10m, 20m) from atmospheric surface signals (air temperature + wind speed) alone. Features:

```
[air_temp_c,  wind_ms,  wind_ms²,  air_temp_c × wind_ms]
```

The quadratic wind term captures turbulent mixing effects; the cross-term captures wind-driven evaporative cooling.

**Two operating modes:**

| Mode            | When Active                   | What the Numbers Mean                              |
|-----------------|-------------------------------|-----------------------------------------------------|
| `verification`  | Sensors live                  | ML predictions compared to actual sensor readings  |
| `estimation`    | Ice-In mode (sensors retracted) | ML predictions are the authoritative temperature state |

**Reading the output:**

- `surface_temp_c`, `predicted_5m_c`, `predicted_10m_c`, `predicted_20m_c`: ML-derived temperatures
- `measured_5m_c`, `measured_10m_c`, `measured_20m_c`: actual sensor readings (null in ice mode)
- Delta (predicted − measured) tells you model accuracy in real time
- `model_r2`: R² coefficient of determination (0–1). Above 0.85 is good. Below 0.5 means the model needs more data or lake conditions are unusual.
- `model_confidence`: normalised to training data size (0–1). Reaches 1.0 after ~200 clean records (≈3 minutes of streaming).
- `records_used`: number of clean records used for the last training run

**Interpreting the R² score:**

| R²       | Meaning                                                          |
|----------|------------------------------------------------------------------|
| 0.9–1.0  | Excellent. Model tracking well.                                  |
| 0.7–0.9  | Good. Minor disagreements likely from local wind events.         |
| 0.5–0.7  | Acceptable. Spring transition or post-turnover creates variance. |
| < 0.5    | Weak fit. Lake is undergoing rapid change (storm, turnover).     |

**Winter operation (Ice-In mode):**
During ice-cover (typically December through mid-March), the thermistor chain is physically retracted to prevent ice damage. The digital twin provides continuous sub-ice temperature estimates using the ML model trained on the previous open-water season. These estimates are less accurate than live sensor data but maintain data continuity for annual trend analysis.

---

## 4. 48-Hour Foresight Risk Scores

**Endpoint:** `GET /foresight`

**What it is:** A physics-based scoring model projecting the 48-hour risk of three ecological hazards. Scores are 0–1 (displayed as 0–100 on the dashboard).

### HAB (Harmful Algal Bloom) Risk

Driven by three factors:
1. **Stratification strength** — a layered water column traps cyanobacteria in the warm, light-rich epilimnion
2. **Wind calming** — below 8 m/s, surface mixing is insufficient to break up surface aggregations
3. **Chlorophyll baseline** — existing algal biomass indicates conditions are already nutrient-rich

**Score interpretation:**

| Score  | Level      | Recommended Action                                                     |
|--------|------------|------------------------------------------------------------------------|
| 0–0.30 | Low        | Routine monitoring. No action required.                                |
| 0.30–0.50 | Moderate | Weekly water sampling. Alert beach managers to watch for scum.        |
| 0.50–0.70 | High    | Intensify sampling to daily. Prepare public advisory language.         |
| > 0.70 | Critical   | Issue HAB advisory. Notify Wisconsin DNR. Close affected beaches.      |

### Anoxia Risk

Driven by:
1. **Thermocline strength** — strong stratification cuts the hypolimnion off from oxygen
2. **Deep water temperature** — warmer deep water accelerates bacterial decomposition (van't Hoff Q₁₀ rule: O₂ consumption doubles per 10°C)
3. **Algal biomass** — more algae = more decomposition when cells sink below the thermocline

**What anoxia means in practice:**
- Cold-water fish (trout, cisco) retreat to deep water in summer. When the hypolimnion becomes anoxic, there is no refuge — fish kills occur.
- Lake Mendota has historically experienced severe hypolimnetic anoxia each summer, driving internal phosphorus loading from sediments.
- Anoxic events typically peak in August–September.

### Turnover Risk

Driven by:
1. **Surface cooling rate** — measured over the last 50 clean readings (~50 seconds of data)
2. **Wind mixing energy** — sustained wind above 8–10 m/s can physically mix the water column
3. **Stratification vulnerability** — a `weakly_stratified` column is closest to the tipping point

**What turnover means:**
- When surface water cools to match deep water density, the thermal barrier collapses.
- The entire water column mixes within hours to days.
- If the hypolimnion was anoxic, the turnover resurfaces oxygen-depleted, H₂S-rich water → fish kills, odour events, and sudden surface cyanobacteria die-off.
- Spring turnover (March–April) is benign — the whole column is already near 4 °C.
- Fall turnover (September–November) is the dangerous event.

---

## 5. Vessel & Recreation Guide

**Endpoint:** `GET /vessel-guide`

This guide evaluates 13 vessel/activity types against four real-time parameters: **wind speed, wave height, water temperature, and chlorophyll-a**.

### Understanding the Status Levels

- **SAFE**: All parameters are within the normal operating envelope for this vessel type.
- **CAUTION**: One or more parameters exceed the caution threshold. Experienced operators may proceed; novices should reconsider.
- **DANGER**: One or more parameters exceed the danger threshold. **Do not launch** regardless of experience.

### Hypothermia Risk Bands

Cold water is the leading cause of recreational fatality on Wisconsin lakes.

| Water Temp | Risk       | Incapacitation | Survival          | Action Required                               |
|------------|------------|----------------|-------------------|-----------------------------------------------|
| < 5 °C     | Critical   | < 7 minutes    | < 30 minutes      | Drysuit mandatory. Rescue vessel on standby.  |
| 5–10 °C    | High       | 7–30 minutes   | 30–60 minutes     | Wetsuit minimum. PFD required. Buddy system.  |
| 10–15 °C   | Moderate   | 30–60 minutes  | 1–6 hours         | Wetsuit recommended. Alert someone of plans.  |
| 15–20 °C   | Low        | 1–2 hours      | 6–12 hours        | PFD recommended. Brief immersion manageable.  |
| > 20 °C    | Negligible | > 2 hours      | Effectively safe  | Standard water safety precautions.            |

**The "Dress for the water, not the air" rule:**
In spring and fall, air temperature may be 18–22 °C while water is 8–12 °C. People dress for the air and fall in unprepared. Hypothermia kills in 30–60 minutes at 8 °C regardless of air temperature.

### Vessel-Specific Decision Points

**Highest-risk vessels (most sensitive to conditions):**
1. **Open water swimmers** — no protection against cold shock, most susceptible to HAB contact
2. **SUP** — highest wind sensitivity; 9 m/s makes upwind return impossible
3. **Rowing shells** — lowest freeboard (5 cm); designed for flat water only; mandatory warm-water-only protocol below 10 °C

**Most resilient vessels:**
1. **Research vessels** — purpose-built for active lake operations; HAB is an occupational hazard handled with PPE
2. **Keelboats** — keel stabilisation and enclosed hull allow operation in stronger wind/chop
3. **Motorboats / pontoons** — engine power overcomes wind resistance; main risk is man-overboard

### When to Cancel an Event (Race Committee / Club Decision)

| Condition                | Recommendation                                                         |
|--------------------------|------------------------------------------------------------------------|
| Wind > 15 m/s sustained  | Cancel all dinghy racing. Post advisory for keelboats.                 |
| Waves > 0.6 m (sig.)     | Cancel rowing events. Dinghy advisory. Keelboats proceed with caution. |
| Water < 7 °C             | No swimming events, no racing in vessels without enclosed hulls.       |
| HAB Advisory (chl > 30)  | Advise against water contact. Cancel triathlon swim legs.              |
| HAB Warning (chl > 70)   | Cancel all water contact activities. Lake management notification.     |
| Turnover risk = high/critical | Post shore notice — possible surface water quality change in 24–48 hrs. |

---

## 6. Data Quality Flags

Every ingested reading carries two quality flags:

### `is_outlier` (Hard Threshold)

**True when:**
- `wind_speed_ms > 20 m/s` — anemometer fault or extreme storm
- `chlorophyll_ugl > 100 µg/L` — fluorometer lens fouling or sensor malfunction

**Behaviour:** Outlier readings are stored but excluded from:
- Rolling wind smoothing buffer
- Digital twin training data
- Stratification calculations
- Foresight scoring

**What it means:** An `is_outlier=True` reading from a fluorometer showing 150 µg/L is almost certainly a dirty lens, not a real bloom. However, if you see 3+ consecutive outlier readings from multiple nodes, it may be worth investigating — rare extreme HAB events can genuinely exceed 100 µg/L.

### `zscore_fouling` (Statistical Detection)

**True when:** |z| > 3.0, where:
```
z = (x − μ) / σ
```
computed over the previous 60 clean readings for that sensor.

**What it catches that hard thresholds miss:**
- A water temperature that jumps from 4.2 °C to 12.1 °C in one reading (plausible value, but physically impossible change rate)
- Gradual sensor drift where a thermistor reads consistently 0.5 °C high — this won't trigger Z-score but is caught during calibration
- Wind sensor that sticks at exactly 6.0 m/s for 10 readings, then suddenly spikes to 18 m/s

**What it does NOT catch:**
- Slow, long-term sensor drift (requires calibration comparison)
- Systematic bias (all readings offset by a fixed amount)

**False positive rate:** With a Z-score threshold of 3.0 and Gaussian noise, a clean sensor will trigger `zscore_fouling=True` about 0.27% of the time by chance. At 1 Hz, expect ~3 false positives per hour per sensor — these are stored but do not corrupt time-series state.

---

## 7. Ice-In Estimation Mode

**Endpoints:** `GET /ice-mode`, `POST /ice-mode`

Lake Mendota typically freezes between late November and early January and thaws between mid-February and late March (historical average ice-out: March 20).

**When to activate:**
- Buoy technicians physically retract the thermistor chain when ice formation is imminent (typically when sustained air temperature drops below −5 °C for 3+ consecutive days).
- Activate Ice-In mode in the API at the same time via the dashboard toggle.

**In estimation mode:**
- The digital twin uses the ML model exclusively for subsurface temperatures.
- Surface air temperature and wind speed (from a shoreside station or the buoy mast if still deployed) drive the predictions.
- Accuracy during ice-cover is lower than open-water (typical error: ±1–2 °C vs. ±0.3–0.5 °C live).
- Data continuity is maintained — no gaps in the 48-hour foresight scoring.

**Turning it off (spring):**
Deactivate Ice-In mode after ice-out is confirmed and the thermistor chain is re-deployed. The digital twin will switch to verification mode immediately, comparing predictions to live sensor readings.

---

## 8. Node Swarm

**Endpoints:** `GET /nodes`, `POST /nodes/register`

The sensor swarm deploys 5 edge nodes at different positions around Lake Mendota to capture spatial heterogeneity:

| Node          | Position           | Primary Purpose                                   |
|---------------|--------------------|---------------------------------------------------|
| node-center   | 43.0988, -89.4045  | NTL-LTER buoy reference position (master)         |
| node-north    | 43.1200, -89.4045  | Northern basin — deeper water, later HAB onset    |
| node-south    | 43.0700, -89.4100  | Southern shallow bay — earliest HAB events        |
| node-east     | 43.0900, -89.3750  | Yahara River inlet — nutrient loading source      |
| node-west     | 43.1050, -89.4400  | Western shore — upwelling zone in SW winds        |

**Reading the node swarm dashboard:**
- **Active** (green pulse): Node sent a reading within the last 30 seconds.
- **Idle** (grey): Node has not reported. May be normal (packet drop) or indicate network/hardware issue.
- **reading_count**: Total telemetry packets accepted from this node since registration.
- **last_seen**: ISO 8601 timestamp of most recent successful ingest.

**Spatial interpretation:**
- If `node-south` shows elevated chlorophyll but `node-center` does not: bloom is nucleating in the shallow south bay (common — warm, nutrient-rich, less wind exposure).
- If `node-east` shows elevated turbidity (not directly measured, but correlated with chl-a spikes): Yahara River runoff event may be supplying phosphorus.
- If nodes have significantly different water temperatures (> 2 °C surface difference): localised upwelling or nearshore heating event.

---

## 9. Decision Trees by User Type

### Recreational User (swimmer, paddler, sailor)

```
1. Check overall_advisory in /vessel-guide
   ├── SAFE   → Check your specific vessel type → proceed if SAFE or CAUTION (experienced)
   ├── CAUTION → Read vessel-specific reasons → decide based on experience
   └── DANGER  → Do not go on the water

2. Check water temperature (hypothermia_risk)
   ├── negligible/low → Dress normally
   ├── moderate       → Bring wetsuit, tell someone your plan
   ├── high           → Wetsuit mandatory, buddy required
   └── critical       → Do not enter water without full drysuit and rescue support

3. Check water quality (water_quality_level)
   ├── excellent/good → No special precautions
   ├── fair           → Rinse off immediately after leaving the water
   ├── poor           → Avoid face-down contact. No children or pets in water.
   └── hazardous      → Stay out of the water entirely
```

### Lake Manager / Beach Director

```
1. Check foresight risk_level at start of each day
   ├── low      → Routine monitoring
   ├── moderate → Prepare advisory communications, schedule water sample
   ├── high     → Issue informal advisory. Contact county health department.
   └── critical → Issue formal HAB advisory. Notify DNR. Close affected beaches.

2. Check stratification_status
   ├── mixed           → Safe window for algaecide/nutrient treatment
   ├── weakly_stratified → Increase sampling frequency
   └── stratified      → Highest risk period. Daily chlorophyll samples minimum.

3. Check turnover risk (in foresight risk_scores.turnover)
   ├── < 0.30 → No action
   ├── 0.30–0.50 → Monitor wind and surface temp closely. Alert fish hatchery.
   └── > 0.50  → Issue waterway advisory. Notify WDNR fisheries. Prepare for possible fish kill.
```

### HAB Responder / DNR Officer

```
1. Trigger condition: foresight risk_level = "critical" AND primary_risk = "hab"
   OR chlorophyll_ugl > 50 µg/L in /status

2. Field response:
   a. Take grab samples within 1 km radius of highest-reading node
   b. Use ELISA test kit for microcystin (> 8 µg/L = recreational closure threshold)
   c. Post signs at all public access points within 24 hours
   d. Notify adjacent municipalities

3. Automated monitoring: poll /foresight every 15 minutes during critical conditions
   └── Track risk_scores.hab: rising trajectory = bloom intensifying
       Falling trajectory = bloom dispersing or mixed out by wind
```

### Researcher / Data Scientist

```
1. Historical time series: GET /readings?n=500 for raw records including outlier flags
   └── Filter is_outlier=False AND zscore_fouling=False for clean series

2. Model performance: GET /digital-twin → model_r2, records_used, mode
   └── R² degradation often signals unusual lake conditions worthy of investigation

3. Stratification phenology: poll /stratification daily
   └── Record first day of stratification_status = "stratified" each year
       Compare to air temperature anomalies for climate trend analysis

4. Spatial analysis: GET /nodes → compare reading_count and timestamps
   └── Node disagreement on chlorophyll > 15 µg/L suggests localised bloom
```

---

## 10. Compound Condition Analysis

The most dangerous scenarios occur when multiple stressors align. These compound conditions require the most urgent response.

### HAB Perfect Storm
**Conditions:** `stratified` + wind < 3 m/s + air_temp > 25 °C + chlorophyll > 20 µg/L + foresight HAB score > 0.6

**Mechanism:** Stratified water column isolates warm, nutrient-rich surface; calm wind prevents mixing; warm temperatures accelerate cyanobacterial growth; existing algae indicate nutrients are available.

**Timeline:** Bloom can develop from near-background to HAB Advisory levels (> 30 µg/L) within 24–48 hours under these conditions.

**Action:** Issue pre-emptive advisory. Close sensitive beaches (children's swim areas, dog parks) 24 hours ahead of bloom peak.

---

### Cold-Water Mass Casualty Scenario
**Conditions:** Water temp < 8 °C + wind > 8 m/s + waves > 0.4 m + weekend (high recreational traffic)

**Mechanism:** Capsize probability increases with wave height; survival time is under 30 minutes; combined with choppy conditions that slow rescue response.

**Lake Mendota context:** This scenario occurs every spring between late March and mid-May. The lake surface may look like summer (blue sky, warm air), but the water is still 5–10 °C.

**Action:** Post cold-water immersion warnings at all marinas and boat launches. Ensure coast guard and fire department swift-water teams are on standby for weekend forecasts.

---

### Fall Overturn + Anoxic Discharge
**Conditions:** `stratified` → `mixed` transition + foresight turnover score > 0.6 + anoxia score > 0.4

**Mechanism:** Thermocline collapse mixes anoxic, sulphide-rich hypolimnetic water to the surface. Sudden oxygen depletion throughout water column.

**Visible signs:** Surface water turns brown/grey; possible fish kill within 24 hours; hydrogen sulphide smell; sudden disappearance of surface algae (toxin release from dying cells).

**Action:** Issue emergency waterway closure. Alert all downstream waterways (Yahara River chain). Notify DNR emergency response. Conduct fish mortality survey.

---

### Winter Ice-Out Flood Risk
**Conditions:** Ice-In mode active + sudden air temp spike > 8 °C for 3+ days + ice thickness unknown

**Mechanism:** Rapid ice-out can produce large ice sheets that move with wind, damaging docks and shoreline structures.

**Action:** Alert marina operators. Remove any floating docks temporarily. Check boat lifts and mooring lines.

---

## 11. Seasonal Calendar

A reference for what to expect each month on Lake Mendota:

| Month | Typical Conditions | Key Watch Points |
|-------|-------------------|-----------------|
| **January** | Full ice cover. Air −15 to −5 °C. | Ice thickness monitoring. No boating. |
| **February** | Peak ice. Possible ice fishing season. | Ice-In mode active. Monitor air temp for early thaw. |
| **March** | Ice-out (average March 20). Rapid warming. | Activate sensors. Spring turnover (~March). Cold water hazard begins. |
| **April** | Post ice-out. Water 5–12 °C. Stratification starting. | Cold water hazard peak. First chl-a readings. Watch for false HAB from diatom bloom. |
| **May** | Water 12–18 °C. Thermocline forming. | Wetsuit season ends. HAB season beginning. First sailing races. |
| **June** | Water 18–22 °C. Stratification established. | First HAB advisory possible. Peak recreational season begins. |
| **July** | Water 22–26 °C. Strong stratification. | Peak HAB risk. Anoxia beginning in deep water. Peak boat traffic. |
| **August** | Water 22–24 °C. Max anoxia. | HAB warning possible. Fish care season. Anoxia at maximum depth. |
| **September** | Surface cooling begins. Water 18–22 °C. | Fall turnover risk rising. Monitor wind for mixing events. |
| **October** | Fall turnover likely. Water 10–15 °C. | Highest turnover risk. Possible fish kill. Cold water hazard returns. |
| **November** | Water 5–10 °C. Pre-freeze. | Retract sensors before ice. Activate Ice-In mode. |
| **December** | Ice formation likely after mid-month. Water 0–5 °C. | Ice hazard. No water activities. |

---

## 12. Alert Response Protocols

### Automated Alert Thresholds (for integration with paging/notification systems)

Poll `GET /foresight` on a schedule appropriate to the season. Suggested frequencies:

| Season     | Poll Frequency | Rationale                                 |
|------------|----------------|-------------------------------------------|
| Dec–Mar    | Every 6 hours  | Low ecological activity; ice-mode monitoring |
| Apr–May    | Every hour     | Spring transition; cold water hazard peak |
| Jun–Sep    | Every 15 min   | Peak HAB and anoxia risk season           |
| Oct–Nov    | Every 30 min   | Fall turnover and cold water risk          |

**Alert thresholds for integration:**

```json
{
  "hab_advisory":    { "field": "risk_scores.hab",     "threshold": 0.50, "level": "high" },
  "hab_warning":     { "field": "risk_scores.hab",     "threshold": 0.70, "level": "critical" },
  "anoxia_watch":    { "field": "risk_scores.anoxia",  "threshold": 0.50, "level": "high" },
  "turnover_watch":  { "field": "risk_scores.turnover","threshold": 0.50, "level": "high" },
  "turnover_alert":  { "field": "risk_scores.turnover","threshold": 0.70, "level": "critical" },
  "cold_water_warning": { "endpoint": "vessel-guide", "field": "hypothermia_risk", "values": ["high", "critical"] },
  "hab_beach_closure":  { "endpoint": "status",       "field": "latest_reading.chlorophyll_ugl", "threshold": 30 }
}
```

### Notification Channels (suggested)

| Alert Level | Channels                                                         |
|-------------|------------------------------------------------------------------|
| Moderate    | Dashboard visual indicator. Email to lake manager.               |
| High        | Dashboard + SMS to beach director + county health liaison.       |
| Critical    | All above + WDNR emergency line + public notification system.    |

### Post-Event Documentation

After any `critical` foresight event:

1. Export raw readings from the event window: `GET /readings?n=500`
2. Document: peak risk score, contributing factors, duration, response actions taken
3. Compare to historical events in NTL-LTER database
4. Update baseline calibration if the event revealed systematic sensor drift

---

*Data from Sentinel-Stream should be used in conjunction with field sampling for regulatory decisions. This system provides continuous early warning, not a substitute for laboratory-certified water quality analysis.*
