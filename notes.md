# Dataset Exploration Notes
Running log of findings. Updated as exploration progresses.

## Database overview

| Metric | Value |
|--------|-------|
| Total tables | 31 (several are views — see below) |
| Total size (approx) | ~400 GB on MySQL |
| Largest table | `sparkmeterreadings` — 363M rows, 347 GB |
| Second largest | `encryptedPhoneNumbers` — 198M rows, 50 GB |
| Countries covered | Kenya, Nigeria |
| Companies | Renewvia Energy Kenya Ltd (REKL), Renewvia Solar Nigeria Ltd (RSNL) |
| Mini-grid sites | 26 total (23 real + 3 test placeholders) |

---

## Table inventory

| Table | In Dict? | Release decision |
|-------|----------|-----------------|
| companies | Yes | Exclude — API credentials |
| countries | Yes | Exclude — no scientific value |
| customers | Yes | Include (partial — drop PII and dynamic fields) |
| exchangerates | Yes | Exclude — better sources available (NREL, IMF, etc.) |
| meteringbasestations | Yes | Exclude — internal operational data only |
| meteringplatformcustomers | Yes | Exclude — currently empty |
| meteringplatformtariffs | Yes | Include |
| minigridprojects | Yes | Include (partial — drop internal/IUO fields) |
| poles | Yes | Exclude — IUO |
| sparkmetercustomers | Yes | Include (partial — drop PII fields) |
| sparkmeterreadings | Yes | Include (partial — drop PII, UncertainMetadata, kilowattHoursPeriod) |
| sparkmetertransactions | Yes | Include (partial — drop PII and IUO fields) |
| tariffs | Yes | Include |
| encryptedPhoneNumbers | No | Exclude — internal anonymization lookup |
| errorlogs | No | Exclude — internal system data |
| gmgCustomers/MeterReadings/MiniGridProjects/Tariffs | No | Exclude — views, no independent data |
| newsteamacocustomers | No | Exclude — internal migration table |
| paymentconfirmations | No | Include (partial — drop PII and IUO fields) |
| paymentreceiptsqueue | No | Exclude — empty |
| paymentvalidations | No | Include (partial — drop PII and IUO fields) |
| poles_v2 | No | Exclude — IUO |
| smsSurveys | No | Exclude — IUO |
| synota/uniMeteringPlatformCustomers/uniMiniGridProjects/uniSparkMeterReadings | No | Exclude — views |
| testingsandbox | No | Exclude — empty, internal |
| vrmgeneration | No | Include (partial — exclude UBA Acme and Shell Oza 1 rows, which are commercial clients not community mini-grids) |

---

## Key findings per table

### `sparkmeterreadings` (core dataset)
- 363 million 15-minute heartbeat records from SparkMeter devices
- Covers multiple metering platforms: `thundercloud`, `koios`, `steamaco`
- Three `meter_type` values: `customer`, `totalizer`, `pue` (Productive Use Equipment)
- **Energy fields**:
  - `kilowattHours` = energy consumed **during this heartbeat period** (kWh) — primary consumption metric
  - `energy` = cumulative kWh consumed by the meter since last reset — useful for detecting meter resets and gap-filling
  - `kilowattHoursPeriod` = purpose unclear; large discrepancy from `kilowattHours` (avg ~1,359, max ~135,000) suggests it may be billing-cycle cumulative; **drop from release**
  - `UncertainMetadata` = internal flag of no analytic value; **drop from release**
- `rate` column typed `decimal(60,30)` — stores tariff rate at time of reading
- PII present: `meter_customer_name`, `meter_customer_phoneNumber`, `meter_address_*`

### `vrmgeneration`
- Victron Energy Remote Monitoring (VRM) telemetry data
- 18 sites covered, Aug 2023 – Dec 2024, ~1-minute resolution
- Key channels: Battery SOC, Battery current/voltage, Solar Charger PV power/current/voltage, System AC Consumption (L1/L2/L3), Generator state, Inverter (VE.Bus) state
- **"UBA Acme, Ogba, Lagos, Nigeria" and "Shell Oza 1" are commercial/industrial clients** — exclude from release; all other 16 sites are community mini-grids
- `testingsandbox` has the identical schema but 0 rows
- Mixed column types: e.g., `PV_Inverter_32_L1_Power` is `varchar(50)` in some device configs — schema-level inconsistency to handle during export

### `paymentconfirmations` and `paymentvalidations`
- validation = initial M-PESA/Paga webhook receipt; confirmation = after metering platform processes it
- **Data quality issues**:
  1. `paymentProcessor` inconsistency: "mpesa" vs "M-PESA" — normalize to lowercase
  2. `transactionDatetime` has NULL and `0000-00-00` dates (~4,700 rows) — early M-PESA records with no date transmitted; time-of-day portion may still be valid
  3. A handful of year=1 or year=2 records — date parsing errors (~5 rows total)
- Date range: 2018–2026; Nigeria (Paga) starting ~2020
- `isReversed` column exists in `paymentconfirmations` but not `paymentvalidations`

### `customers`
- 12,820 customer records
- Demographics: mostly residential (~76%), active (~84%), male (~54%), female (~31%), NULL gender (~15%)
- Rich `customerType` taxonomy: Residential, Shop, Bar/Restaurant, Church, School, Health Clinic, Kinyozi/Salon, Workshop, NGO, Video Hall, Battery Charging, Guest House, Conference Hall, Mosque, etc.
- `customerStatus`, `tags`, `latestReading`, `status` are dynamic snapshots — no scientific value; exclude
- `formFiller` is a staff member's name — PII; exclude
- Columns not in original dictionary: `customerId`, `meterOnPlatform`, `dcuId`, `signupPaymentProcessed`, `latestReading`, `status`

### `minigridprojects`
- 26 projects: 15 Kenya + 11 Nigeria (including 3 test placeholders with lat/long = 0,0)
- All real projects are PV Solar generation
- Capacity range: ~6 kWp (Olkiramatian) to ~541 kWp (Kalobeyei Settlement)
- Battery range: 14.8 kWh (Balep) to 1,105 kWh (Kalobeyei Settlement)
- Kalobeyei Settlement is a UNHCR refugee settlement — the largest site by far
- All Kenya sites are UTC+3; Nigeria sites are UTC+1
- PVWatts fields (`pvwatts*`) are derived from NREL's PVWatts tool — exclude (source data available from NREL)
- `investors`, `donors`, `remoteMonitoring*` — no scientific value or IUO; exclude

### `meteringbasestations`
- 58 rows; one base station per metering zone
- Kalobeyei Settlement has 13+ base stations because the settlement is very large (~500 m range limit per base station)
- Contains operational credentials (auth tokens, passwords, SIM cards, IPs) — exclude entirely

### `tariffs`
- 870 rows across all sites
- Many rows have `baseRate = 0`, `totalRate = 0` — historical placeholder rows from system setup
- `startingDatetime` tracks when each rate took effect (allows reconstructing historical effective rate for any reading)

### `sparkmetercustomers`
- Private address/location fields: `meters_address`, `meters_city`, `meters_coords`, `meters_country`, `meters_street1`, `meters_street2`, `meters_tags` — exclude
- `name`, `phoneNumber` — PII; exclude

### `sparkmetertransactions`
- `referenceId`, `externalId`, `memo` — internal use only; exclude
- `to_name`, `from_name` could contain customer display names — exclude

### `exchangerates`
- Daily USD exchange rates for KES and NGN, 2018–2026
- Better and more authoritative sources exist online (World Bank, IMF, NREL) — exclude from release

---

## Data quality issues summary

| Issue | Table(s) | Severity | Notes |
|-------|----------|----------|-------|
| `paymentProcessor` inconsistent case | paymentconfirmations, paymentvalidations | Medium | "mpesa" vs "M-PESA"; normalize to lowercase |
| `transactionDatetime` = 0000-00-00 or NULL | paymentconfirmations, paymentvalidations | Medium | ~4,700 rows; early M-PESA records missing date |
| `transactionDatetime` year = 1 or 2 | paymentconfirmations, paymentvalidations | Low | ~5 rows; date parsing errors |
| `kilowattHoursPeriod` purpose unclear | sparkmeterreadings | Low | Drop from release |
| Tariff rows with rate = 0 | tariffs | Low | Historical placeholders; document as such |
| `customerType` trailing spaces | customers | Low | e.g., "Institution " |
| GPS = 0,0 for test sites | minigridprojects | Low | 3 test projects; exclude from release |
| `vrmgeneration` mixed column types | vrmgeneration | Low | PV_Inverter_32_L1_Power is varchar on some devices |

---

## PII inventory (for anonymization)

| Table | PII columns |
|-------|-------------|
| customers | name1, name2, name3, name, phoneNumber, formFiller |
| sparkmetercustomers | name, phoneNumber, meters_address, meters_city, meters_coords, meters_street1/2 |
| sparkmeterreadings | meter_customer_name, meter_customer_phoneNumber, meter_address_street1/2/city/state/postalcode |
| sparkmetertransactions | to_customer_name, to_customer_phoneNumber, to_name, from_customer_name, from_customer_phoneNumber, from_name, to/from_address_* |
| paymentconfirmations | firstName, middleName, lastName, phoneNumber |
| paymentvalidations | firstName, middleName, lastName, phoneNumber |
| smsSurveys | phoneNumber (table excluded) |
| encryptedPhoneNumbers | phoneNumber (table excluded) |

Identifiers to pseudonymize (consistent token across tables): `customerAccountNumber`, `customerId`, `meter_customer_id`, `meter_customer_code`, `meter_customer_code_backup`, `to_customer_id`, `to_customer_code`, `from_customer_id`, `from_customer_code`.

---

## Anonymization strategy (draft)

1. **Customer pseudonymization**: Replace `customerAccountNumber`, `customerId`, and all customer code fields with SHA-256(account_number + secret_salt). Must be consistent across all tables.
2. **Phone number removal**: Drop all phone number columns entirely.
3. **Name/address removal**: Drop all name and street address fields from all tables.
4. **Credentials**: Drop all credential columns; exclude `companies` and `meteringbasestations` tables entirely.
5. **Payment tables**: Normalize `paymentProcessor` to lowercase. Flag records with 0000-00-00 dates.
6. **vrmgeneration**: Exclude UBA Acme and Shell Oza 1 rows before release.
7. **minigridprojects**: Exclude the 3 test sites (lat/long = 0,0).

---

## Visualization ideas for Scientific Data paper

1. **ARPU and ACPU** over time for different customer types and geographies
2. **Load profiles** of archetypical customers, average 24-hour profile
3. **Comparison** of customer consumption behavior to equivalent data from major cities, rural US farming communities, etc.
4. **Tariff evolution**: Rate per kWh over time per site
5. **Data completeness matrix**: Table × site × year showing % completeness
6. **Meter uptime**: From `sparkmeterreadings` `uptime` field, mean uptime by site over time
7. **Carbon accounting** per kWp capacity, per customer, and per USD CAPEX using the UNFCCC AMS-III.BB.
8. **Power quality**: average voltage vs. power factor, histograms of minimum, average, and maximum voltages
9. **Grid losses**: histogram of percentage of power lost

---

## Answers to follow-up questions

**`sparkmeterreadings` date range**: 2018-04-19 to 2025-12-16. There are 183,330 records with `heartbeatStart = 1970-01-01 00:00:00` (Unix epoch zero — corrupted timestamps, ~0.05% of total). All other timestamps are valid. These epoch-zero rows should be filtered out of the release.

**`meter_customer_code` = `customerAccountNumber`**: Direct equality join confirmed. This is the primary cross-table pseudonymization key. Note: `customers.customerId` is NULL for most rows and is not useful as a join key; use `customerAccountNumber` / `meter_customer_code` instead.

**`sparkmeterreadings.site` UUID**: Maps directly to `meteringbasestations.meteringSiteId`. Use this join to resolve site names for analysis. Confirmed 17 distinct active sites in mid-2024 data (see [04_followup_questions.sql](explore/04_followup_questions.sql) for full list).

**`rate` field in `sparkmeterreadings`**: Stores the effective tariff `totalRate` (local currency per kWh) at the time of the reading. Confirmed by checking Akipelai Residential: the `tariffs` table shows rates of 224.68 → 258.00 → 356.79 → 346.38 → 430.00 NGN/kWh over 2023–2024, and the `rate` field in readings reflects these transitions. The join path is `sparkmeterreadings.site → meteringbasestations.meteringSiteId → meteringbasestations.meteringBaseStation → tariffs`. The `rate` column is therefore derivable from `tariffs` + `meteringbasestations` — consider whether to keep it in the release (it's useful for per-reading cost calculations, and the `decimal(60,30)` type is unwieldy but the values are reasonable).

**`state` codes**: From a 1-day sample: 0, 1, 9, 13 observed. State 1 (~74%) = normal active operation; state 0 (~14%) = off/unpowered; state 13 (~11%) = likely low credit; state 9 (~1%) = tamper detected. Full definitions at SparkMeter support docs (linked in Data Dictionary).

**`truePowerAvg` vs `truePowerInst`**: `truePowerAvg` = mean true power over the 15-minute period (W). `truePowerInst` = instantaneous true power reading at the END of the period. Usually equal; they differ when load changes mid-period. `truePowerInst=0` with `truePowerAvg>0` indicates the meter was disconnected at the end of the heartbeat.

**`isReversed` in `paymentconfirmations`**: Only 3 records ever have `isReversed=1`. The field was added retroactively; ~1M records have NULL. Reversals are negligible and the field provides almost no scientific value.

**`meters_coords` in `sparkmetercustomers`**: NOT GPS coordinates — values are wiring color codes ("RED", "YELLOW"). Already excluded. (lat/lon string?)

## Lit review
https://www.researchgate.net/publication/346332520_Classification_and_modeling_of_load_profiles_of_isolated_mini-grids_in_developing_countries_A_data-driven_approach
https://www.researchgate.net/publication/303564531_Assessment_of_Load_Profiles_in_Minigrids_A_Case_in_Tanzania
https://www.sciencedirect.com/science/article/pii/S0301421523005542
https://pubs.naruc.org/pub.cfm?id=A1E7A0F1-155D-0A36-319F-8CBC8BE8B342
https://scispace.com/pdf/the-impact-of-an-electrical-mini-grid-on-the-development-of-5e2j24qpix.pdf
One of our previous publications: https://iopscience.iop.org/article/10.1088/2634-4505/ad4ffb
https://www.researchgate.net/publication/400672774_Overcoming_Technical_and_Operational_Barriers_in_Low-Voltage_Mini-Grids_Two_Decades_of_Research_Trends_Progress_and_Pathways_for_Accelerated_Rural_Electrification_2005-2025
https://www.mdpi.com/1996-1073/19/6/1441
https://www.frontiersin.org/journals/energy-research/articles/10.3389/fenrg.2022.1089025/full