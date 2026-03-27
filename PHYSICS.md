# Sentinel-Stream — Physical Basis

This document explains every physical and mathematical model used in the pipeline.
It covers the emulator's synthetic data generation, the signal quality filters,
the digital twin predictor, and the foresight risk scoring system.  Where
applicable, parameter values are cited against the primary literature or NTL-LTER
field observations for Lake Mendota.

---

## 1. Lake Mendota Physical Context

Lake Mendota is a 39.4 km² dimictic (two-turnover-per-year) lake in Madison, WI.
Depth: 25.6 m maximum, 12.8 m mean.  The NTL-LTER research buoy is anchored at
43.0988° N, 89.4045° W, approximately 1.5 km NE of Picnic Point.

**Seasonal thermal cycle (relevant to all models below):**

| Period | Surface (0 m) | Deep (20 m) | Δt | State |
|---|---|---|---|---|
| Winter (Jan–Mar) | 0–1°C (ice) | ~4°C | −3 to −4°C | Inverse stratification |
| Spring turnover (Mar–Apr) | ~4°C | ~4°C | ~0°C | Fully mixed |
| Spring warming (Apr–Jun) | 8–18°C | 4–7°C | 4–14°C | Weakly → stratified |
| Summer (Jul–Aug) | 22–26°C | 6–9°C | 14–20°C | Strongly stratified |
| Fall turnover (Oct–Nov) | ~10°C | ~10°C | ~0°C | Fully mixed |

*Source: NTL-LTER high-frequency data 1981–present; Benson et al. 2000.*

---

## 2. Sensor Emulator — Synthetic Data Generation

### 2.1 Baseline conditions (late March, post ice-out)

The emulator targets late March because the NTL-LTER buoy is typically deployed
after ice-out (historically mid-to-late March in Madison) and retracted in
November.  Immediately post ice-out, the water column is *nearly isothermal at
~4°C* — the temperature of maximum freshwater density — because winter convective
mixing has erased all stratification.

```
BASE_AIR_TEMP_C   =  6.0°C   (Madison WI late-March daily mean: 5–8°C)
BASE_WIND_MS      =  6.0 m/s  (prevailing SW lake exposure)
BASE_WATER_TEMP   =  0m: 4.0°C, 5m: 3.8°C, 10m: 3.6°C, 20m: 3.4°C
BASE_CHLOROPHYLL  =  6.5 µg/L  (NTL-LTER observed range Mar: 2–12 µg/L)
```

The slight cooling with depth in the baseline (4.0 → 3.4°C) reflects the
residual inverse-stratification signature from the underside of the ice cover,
which is still eroding during the first weeks after ice-out.

### 2.2 Diurnal air temperature cycle

```python
diurnal_air = 4.0 * np.sin(2π × sequence / 86400)
```

A ±4°C sinusoidal diurnal cycle around the 6°C baseline gives an 8°C
peak-to-trough daily range.  NOAA data for Madison in March shows mean daily
temperature ranges of 8–12°C, placing this on the low-moderate end of
climatologically realistic values.

The sine phase is such that `sequence = 0` corresponds to midnight (sin = 0,
rising toward peak at sequence ≈ 21 600, which is 6 hours after start).

### 2.3 Diurnal water temperature — surface and depth attenuation

```python
surface_diurnal = 0.3 * np.sin(2π × sequence / 86400)

attenuation = {
    "0m":  1.0,   # full amplitude at surface
    "5m":  0.6,   # 60% — mixed layer extends through this depth in spring
    "10m": 0.2,   # 20% — below effective mixing depth
    "20m": 0.0,   # hypolimnion completely decoupled from diurnal forcing
}
```

**Amplitude (±0.3°C):** In spring, the entire water column (~4°C) acts as a
large thermal reservoir with no thermocline to trap heat near the surface.
Solar heating is distributed rapidly by wind mixing through the full mixed layer,
producing a small diurnal surface signal (~0.2–0.5°C; Staehr et al. 2010).
In summer, the established thermocline traps shortwave energy in the epilimnion
and the surface diurnal amplitude grows to ~1.5°C.

**Depth attenuation:** Diurnal thermal signals propagate downward through two
mechanisms: (a) molecular diffusion and (b) turbulent wind-driven mixing.
The penetration depth for molecular conduction alone is:

```
δ = sqrt(2α / ω)
  = sqrt(2 × 1.4×10⁻⁷ m²/s  /  (2π / 86400 s))
  ≈ 0.062 m   (6 cm)
```

where α is the molecular thermal diffusivity of water (1.4×10⁻⁷ m²/s) and
ω = 2π/T is the diurnal angular frequency.  This near-zero penetration depth
means that in a *quiescent* lake, diurnal warming is confined to the top
few centimetres.

However, wind-driven turbulent mixing increases the effective diffusivity by
2–4 orders of magnitude (α_turbulent ~ 10⁻⁴ to 10⁻³ m²/s in the actively
mixed layer).  In the spring well-mixed state:

```
δ_turbulent = sqrt(2 × 10⁻⁴  /  7.27×10⁻⁵) ≈ 1.7 m
```

The mixed layer in early spring on Mendota extends 5–15 m (entire column is
effectively mixing), so the attenuation factors used (60% at 5m, 20% at 10m)
are physically justified as representative of moderate mixing conditions.

### 2.4 Sensor noise standard deviations

| Sensor | σ | Instrument basis |
|---|---|---|
| Air thermistor | ±0.25°C | Typical NTC thermistor accuracy ±0.2°C plus digitization noise |
| Cup anemometer | ±0.4 m/s | Standard anemometer accuracy ±0.3–0.5 m/s at moderate winds |
| Water thermistors | ±0.15°C | Higher-grade underwater thermistor chain (HOBO U22) accuracy ±0.2°C |
| Fluorometer | ±0.8 µg/L | Turner Cyclops-7 sensor: ~12% relative noise at 6.5 µg/L baseline |

Noise is modelled as zero-mean Gaussian (white noise), which is appropriate
for instrument electronics noise.  Real-world sensor noise also includes
low-frequency drift and biofouling bias, modelled separately by the fault
injection system (Section 2.5).

### 2.5 Fault injection

Two fault modes are injected to exercise the pipeline's quality-control logic:

**Packet drop (default 10%):** Models LoRaWAN / Wi-Fi link loss between buoy
and shore station.  Real NTL-LTER telemetry achieves 90–95% delivery rate in
clear conditions.

**Outlier injection (default 5%):** Alternates between:
- Wind spike: 25–40 m/s (anemometer saturation or mechanical fault)
- Chlorophyll spike: 110–200 µg/L (fluorometer lens fouling by biofilm)

---

## 3. Signal Quality Filters

### 3.1 Hard-threshold outlier detection

```
wind_outlier     = wind_speed_ms   > 20.0 m/s
chl_outlier      = chlorophyll_ugl > 100.0 µg/L
is_outlier       = wind_outlier OR chl_outlier
```

**Wind threshold (20 m/s):** Beaufort force 9 (severe gale) on an inland lake.
Climatological wind data for Lake Mendota shows gusts exceeding 20 m/s less than
0.01% of the time; a sustained reading above this threshold is overwhelmingly
likely to indicate sensor saturation or mechanical fault rather than a real event.

**Chlorophyll threshold (100 µg/L):** The maximum credible bloom concentration
for Lake Mendota.  The historic peak measured bloom chl-a on Mendota is
~120 µg/L (Lathrop et al. 1998), but individual 1 Hz fluorometer readings
above 100 µg/L are far more likely to indicate optical fouling (biofilm on the
sensor lens, debris in the optical path) than a genuine bloom at that instant.

Outlier records are stored with `is_outlier = True` rather than discarded.
This preserves the forensic audit trail for post-incident analysis (e.g.,
correlating a false HAB alert with a fluorometer fouling event).

### 3.2 Z-score sensor fouling detector

```
z(x) = |x − μ_window| / σ_window

zscore_fouling = any z(x) > 3.0   (for air_temp, wind, water_temp_0m, chlorophyll)
```

where the rolling window length is 60 readings (60 seconds at 1 Hz).

The Z-score filter is complementary to the hard-threshold filter:

- Hard threshold catches **absolute** implausibility (physically impossible values)
- Z-score filter catches **relative** implausibility (values that are technically
  within physical bounds but are statistically impossible given recent history —
  i.e., sudden spikes that the hard threshold misses)

**Example:** A water temperature reading of 12°C is physically plausible in
summer, so it passes the hard threshold.  But if the rolling mean is 3.9°C
(spring) and σ = 0.15°C, then z = (12 − 3.9) / 0.15 = 54 — clearly a sensor
fault, not a real 8°C jump in one second.

The minimum window size for Z-score computation is 15 samples.  Below this,
there is insufficient baseline to compute a meaningful standard deviation.

**Statistical note:** A threshold of z > 3.0 corresponds to flagging observations
more than 3 standard deviations from the rolling mean.  Under a normal
distribution, this has a false-positive rate of ~0.26% per sensor per reading.
With 4 sensors checked per ingest cycle, the combined false-positive rate is
~1% at steady state — a tolerable trade-off for catching real fouling events.

### 3.3 Rolling-window wind smoothing

```
smoothed_wind = mean(last 10 clean wind readings)
```

A 10-point boxcar filter at 1 Hz provides a 10-second smoothing window.
This suppresses instrument noise from cup anemometer vibration and eddy gusts
without lagging behind genuine wind speed changes (which on an inland lake
typically evolve over timescales of minutes).  Outlier readings are excluded
from the buffer to prevent a single fault from corrupting 10 subsequent
smoothed values.

---

## 4. Digital Twin — Physics-Informed ML Predictor

### 4.1 Problem statement

When the physical thermistor chains are retracted for winter (Ice-In mode),
the only available atmospheric measurements are air temperature and wind speed.
The digital twin must infer the full subsurface temperature profile from these
surface-only observations.

### 4.2 Physical feature engineering

The model maps four physics-motivated features to four depth targets:

```
X = [T_air,  U_wind,  U_wind²,  T_air × U_wind]
y = [T_0m,   T_5m,    T_10m,    T_20m]
```

Each feature encodes a known physical mechanism:

| Feature | Physical mechanism |
|---|---|
| T_air | Sensible heat flux at the air-water interface (Q_H ∝ C_H · U · (T_air − T_surf)) |
| U_wind | Wind-driven shear stress on the lake surface (τ = ρ_air · C_D · U, linear term) |
| U_wind² | Wind stress mechanical energy input (E_mixing ∝ U²); dominant mixing driver |
| T_air × U_wind | Coupling term: Q_H ∝ U · ΔT; captures that cooling is faster when both air is cold AND wind is strong |

**Why these features and not others?**  Solar irradiance is the dominant
driver of lake heating but is not measured at the buoy.  Longwave radiation
and latent heat flux (evaporation) are also unmeasured.  Among the variables
that *are* measured, air temperature and wind are the most physically
informative proxies for the net surface heat budget.

**Why Ridge regression?**  The four features are correlated (T_air and wind
vary together during weather systems), which destabilises ordinary least
squares.  Ridge regression adds an L2 penalty (α = 1.0) that shrinks
coefficients, preventing overfitting on the correlated input space and
producing physically stable predictions during extrapolation — essential
for the Ice-In estimation scenario.

### 4.3 Expected model behaviour

At steady state (1 Hz, 500 records in training window), the model captures
two key physical relationships:

1. **Thermal inertia increases with depth:** The 20m hypolimnion responds
   much more slowly to surface forcing than the 0m epilimnion.  The Ridge
   coefficients for T_20m should be smaller in magnitude and the predictions
   more stable (less variance) than for T_0m.

2. **Wind mixing homogenises the column:** High U_wind² should push
   predicted T_5m, T_10m, T_20m closer to T_0m (stratification erodes).
   Low U_wind² allows the column to stratify (deeper layers decouple from
   surface).

**Limitation — no temporal memory:** The model is trained on individual records
(no time-series features), so it cannot capture hysteresis effects (e.g., the
fact that a lake that has been stratified for 2 weeks behaves differently from
one that became stratified yesterday).  A true LSTM/transformer would capture
this; Ridge regression with instantaneous features is a deliberate simplification
appropriate for an edge-compute prototype on a Raspberry Pi-class device.

### 4.4 Training window and staleness

The model trains on the 500 most recent clean records and is retrained every
100 new records.  At 1 Hz with 5 nodes, this means the model is refreshed
approximately every 20 seconds, ensuring it remains calibrated to the current
seasonal state of the lake.

---

## 5. Thermal Stratification Classification

```python
Δt = T_0m − T_20m

if   Δt ≥ 10.0°C:  "stratified"
elif Δt ≥ 4.0°C:   "weakly_stratified"
else:              "mixed"
```

**Physical basis:**
The temperature difference between the epilimnion (0m) and hypolimnion (20m)
is a direct proxy for the density difference driving stratification.  Freshwater
density is approximately linear in temperature for the 4–25°C range relevant
to Mendota:

```
ρ(T) ≈ 999.84 − 0.0068 × (T − 4)²   kg/m³   (simplified quadratic near T_max_density)
```

For Δt = 10°C (e.g., 20°C surface, 10°C deep):
```
Δρ ≈ 0.0068 × (16² − 36) ≈ 1.5 kg/m³
```
This density contrast is sufficient to strongly resist wind-driven mixing
(Schmidt stability > 100 J/m² in Mendota summer conditions).

For Δt = 4°C (e.g., 8°C surface, 4°C deep):
```
Δρ ≈ 0.0068 × (16 − 0) ≈ 0.1 kg/m³
```
This weak gradient is easily overcome by moderate winds — correctly classified
as "weakly stratified."

For Δt < 4°C (post ice-out spring): column is essentially isothermal —
wind mixing can penetrate to the full depth.

**Note on inverse stratification (winter):** In winter with ice cover,
T_0m ≈ 0°C and T_20m ≈ 4°C, giving Δt ≈ −4°C.  This is physically distinct
from a "mixed" column — it is inversely stratified due to the anomalous density
maximum of water at 4°C.  The current threshold classifies this as "mixed"
(Δt < 4°C), which is an acknowledged simplification.  The Ice-In mode flag
provides the semantic context that true winter-under-ice conditions are active.

---

## 6. Foresight Risk Scoring — 48-Hour Hazard Assessment

The foresight model scores three independent hazard categories using a linear
weighted combination of normalised indicator variables derived from current
sensor state.  Scores range [0, 1]; the dominant risk category and its score
are returned as the actionable output.

### 6.1 HAB (Harmful Algal Bloom) risk

```
strat_w     = {stratified: 0.80, weakly_stratified: 0.45, mixed: 0.10}
chl_w       = min(1.0,  chl / 50.0)
wind_calm_w = max(0.0,  1.0 − wind / 8.0)

HAB_score   = 0.40 × strat_w + 0.35 × chl_w + 0.25 × wind_calm_w
```

**Physical basis:**

Cyanobacterial blooms (the primary HAB concern on Lake Mendota) require three
simultaneous conditions:

1. **Thermal stratification** allows buoyancy-regulating cyanobacteria to
   accumulate at the depth of optimal light and nutrients, typically the top
   0–3 m of the epilimnion.  The `strat_w` factor weights this: a stratified
   column provides the stable, layered environment that bloom-forming genera
   (Microcystis, Aphanizomenon) exploit.

2. **Chlorophyll-a** is the primary proxy for algal biomass, encoding both
   the existing biomass capable of rapid bloom expansion and the nutrient
   conditions (phosphorus-limited growth) that sustain it.  The Wisconsin DNR
   issues elevated concern advisories at ~20 µg/L and high-risk advisories
   at ~70 µg/L.  The factor saturates at 50 µg/L (chl_w = 1.0), consistent
   with the midpoint of that advisory range.

3. **Low wind mixing** is the critical trigger.  Studies on Lake Mendota and
   comparable lakes (Paerl & Huisman 2008; Webster et al. 2000) demonstrate
   that sustained wind speeds above 5–8 m/s erode the thermocline, mixing
   buoyant cells below the photic zone and disrupting bloom formation.  The
   saturation threshold of 8 m/s is calibrated to the lower end of this
   empirical range to be conservative (err toward flagging risk rather than
   missing a bloom).

**Weight rationale:** Stratification (40%) is the dominant factor because without
it, cyanobacteria cannot maintain position in the photic zone regardless of
nutrient levels.  Chlorophyll (35%) directly measures the biomass "fuel" for
bloom expansion.  Wind (25%) acts as a moderating control.

### 6.2 Anoxia risk

```
thermo_w  = min(1.0,  thermocline_strength / 15.0)
deep_w    = min(1.0,  max(0.0, (T_20m − 4.0) / 6.0))

Anoxia_score = 0.60 × thermo_w + 0.25 × deep_w + 0.15 × chl_w
```

**Physical basis:**

Hypolimnetic anoxia occurs when the deep layer is physically isolated from
surface oxygen exchange long enough for aerobic decomposition to consume
dissolved oxygen below the 2 mg/L hypoxia threshold.

1. **Thermocline strength** (60% weight): The primary driver.  A stronger Δt
   represents a denser interface that resists the wind mixing needed to re-oxygenate
   the hypolimnion.  The 15°C saturation point corresponds to a strong mid-summer
   Mendota stratification event.

2. **Deep water temperature** (25% weight): Biological oxygen demand (BOD) of
   the decomposing organic sediment scales with temperature — approximately
   doubling per 10°C following the van't Hoff Q₁₀ rule.  The Lake Mendota
   hypolimnion at 20m varies from ~4°C (spring isothermal) to ~9–10°C (late
   summer peak).  The normalisation uses a 6°C working range (4°C → 0, 10°C → 1)
   calibrated to Mendota's observed hypolimnion temperature record.

3. **Chlorophyll-a** (15% weight): Higher algal biomass increases the organic
   load settling to the sediment, increasing hypolimnion BOD.  Acts as a
   secondary fuel term for decomposition-driven O₂ demand.

### 6.3 Turnover risk

```
cooling_w  = min(1.0, max(0.0, −slope / 0.001))  # slope in °C/s from 50-record OLS
wind_mix_w = min(1.0, wind / 15.0)
vuln_w     = {weakly_stratified: 0.90, stratified: 0.40, mixed: 0.10}

Turnover_score = 0.35 × cooling_w + 0.35 × wind_mix_w + 0.30 × vuln_w
```

**Physical basis:**

Lake turnover (fall overturn on Mendota, typically October–November) occurs
when the surface layer cools to match the density of the hypolimnion, eliminating
the stratification that prevented wind mixing.  Three conditions interact:

1. **Rapid surface cooling** (35%): The rate of epilimnion cooling is computed
   via OLS regression over the 50 most recent clean readings (~50 seconds at 1 Hz).
   The normalisation saturates at −0.001°C/s = −3.6°C/hour — a cooling rate
   consistent with strong cold-front passage.  The 50-reading window also reduces
   noise-induced false positives: with σ_temp = 0.15°C, the OLS slope noise floor
   over 50 readings is ≈ ±0.0004°C/reading, comfortably below the 0.001 saturation.

2. **Wind mixing energy** (35%): High wind both accelerates heat loss from the
   surface (via latent and sensible heat flux) and directly drives mechanical
   mixing.  The 15 m/s saturation is set above storm-force wind for this inland
   lake (Beaufort force 8 = 17.2–20.7 m/s; maximum credible sustained lake
   wind is ~15–18 m/s).

3. **Column vulnerability** (30%): Physical vulnerability to mixing depends on
   how close the water column is to neutral stratification:
   - **Weakly stratified (0.9):** The thermocline is already eroding; a moderate
     wind event can complete the overturn.
   - **Stratified (0.4):** Strong stratification delays but doesn't prevent
     overturn; eventual turnover will be more dramatic (larger anoxic water
     mass reaching the surface).
   - **Mixed (0.1):** Column is already overtured; no stored stratification energy
     to release.  Risk is minimal.

### 6.4 Aggregate risk and thresholds

```
risk_score  = max(HAB_score, Anoxia_score, Turnover_score)
primary_risk = argmax of above

risk_level:
  critical  ≥ 0.70
  high      ≥ 0.50
  moderate  ≥ 0.30
  low        < 0.30
```

The thresholds (0.70 / 0.50 / 0.30) are calibrated such that:

- **Low (< 0.30):** All individual factor inputs at or below half their
  maximum values; no single strong driver present.  Routine monitoring.
- **Moderate (0.30–0.50):** One or two factors elevated; developing conditions
  that warrant increased monitoring frequency.
- **High (0.50–0.70):** Multiple factors simultaneously elevated; conditions
  that historically precede hazard events on Lake Mendota within 24–72h.
- **Critical (≥ 0.70):** All major factors in the high-risk range; immediate
  advisory action warranted.

---

## 7. Summary of Physics Corrections from Initial Implementation

During code review, four discrepancies between the implementation and the
physical literature were identified and corrected:

| # | Location | Original | Corrected | Reason |
|---|---|---|---|---|
| 1 | `sensor_emulator.py` line comment | "±1.5°C amplitude" | "±0.3°C amplitude" | 1.5°C is summer amplitude; spring post-ice-out is 0.3°C |
| 2 | HAB `wind_calm_w` | `1.0 − wind / 12.0` | `1.0 − wind / 8.0` | Mendota bloom suppression observed at 5–8 m/s; 12 m/s threshold was too permissive |
| 3 | Anoxia `deep_w` | `(T_20m − 4.0) / 20.0` | `(T_20m − 4.0) / 6.0` | Mendota hypolimnion at 20m reaches 9–10°C, not 24°C; /20 made the factor near-zero under all realistic conditions |
| 4a | Turnover `cooling_w` | `-slope / 0.003` over 30 records | `-slope / 0.001` over 50 records | 0.003°C/s would fire on instrument noise; 0.001°C/s aligns with detectable precursor cooling rates; longer window reduces noise variance |
| 4b | Turnover `vuln_w` | `mixed: 0.3, stratified: 0.2` | `mixed: 0.1, stratified: 0.4` | A mixed column has no stored stratification energy to release (already overturned); a stratified column has more energy and higher eventual turnover risk than an already-mixed one |

---

## 8. References

- Benson, B.J. et al. (2000). *Contrasting lake and catchment responses to climate change.* NTL-LTER data report.
- Lathrop, R.C. et al. (1998). *Phosphorus loading reductions needed to control blue-green algal blooms in Lake Mendota.* Can. J. Fish. Aquat. Sci.
- NTL-LTER High-Frequency Meteorological/Dissolved Oxygen/Chlorophyll Data. https://lter.limnology.wisc.edu
- Paerl, H.W. & Huisman, J. (2008). Blooms like it hot. *Science* 320: 57–58.
- Staehr, P.A. et al. (2010). Lake metabolism and the diel oxygen technique. *Limnology & Oceanography: Methods* 8: 628–650.
- Webster, K.E. et al. (2000). Structuring features of lake districts. *Freshwater Biology* 43: 499–515.
- Wetzel, R.G. (2001). *Limnology: Lake and River Ecosystems*, 3rd ed. Academic Press.
