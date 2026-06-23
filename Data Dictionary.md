# MySQL Database Data Dictionary — Renewvia Mini-Grid Management System

> Tables are listed alphabetically. **[EXCLUDE]** = not included in public release. **[VIEW]** = database view with no independent data. Within included tables, columns marked **[EXCLUDE]** are dropped from the release. Columns marked **[PSEUDONYMIZE]** are replaced with a consistent opaque token.

---

## Table: companies **[EXCLUDE]**
**Reason**: Contains API credentials.

---

## Table: countries **[EXCLUDE]**
**Reason**: No scientific value; coverage (Kenya, Nigeria) is documented in `minigridprojects`.

---

## Table: customers
**Purpose**: Core customer registry. One row per customer connection. 12,820 rows.

| Column | Type | Release |
|--------|------|---------|
| customerAccountNumber | varchar(45) PK | **[PSEUDONYMIZE]** Unique customer identifier |
| name1 | varchar(100) | **[EXCLUDE]** PII |
| name2 | varchar(100) | **[EXCLUDE]** PII |
| name3 | varchar(100) | **[EXCLUDE]** PII |
| name | varchar(300) | **[EXCLUDE]** PII |
| meteringBaseStation | varchar(100) | Base station the customer's meter is registered to |
| projectName | varchar(100) FK→minigridprojects | Mini-grid project name |
| poleNumber | varchar(45) | Local pole number within the site |
| poleNumberGlobal | varchar(45) | Global pole identifier (site code + local pole number) |
| meterType | varchar(45) | Meter hardware type |
| meterSerial | varchar(45) | Meter serial number |
| phoneNumber | varchar(45) | **[EXCLUDE]** PII |
| tariff | varchar(45) | Assigned tariff name |
| customerType | varchar(100) | Customer category (Residential, Shop, School, Health Clinic, etc.) |
| customerStatus | varchar(45) | **[EXCLUDE]** Dynamic snapshot; no scientific value |
| createdTime | datetime | Account creation timestamp |
| formFiller | varchar(45) | **[EXCLUDE]** Staff member name — PII |
| meterRole | varchar(100) | Role of the meter connection (e.g., main, sub) |
| isPostpaid | tinyint | 1 if customer is on postpaid billing |
| gender | varchar(45) | Customer gender (Male, Female, Other, NULL) |
| householdSizeMales | int | Number of male household members |
| householdSizeFemales | int | Number of female household members |
| householdSizeOthers | int | Number of other household members |
| tags | varchar(1000) | **[EXCLUDE]** No scientific value |
| customerId | varchar(45) | **[PSEUDONYMIZE]** Platform-specific customer ID |
| meterOnPlatform | varchar(45) | Whether the meter is registered on the metering platform |
| dcuId | varchar(45) | DCU (Data Concentrator Unit) identifier |
| signupPaymentProcessed | tinyint | 1 if the initial signup payment has been processed |
| latestReading | datetime | **[EXCLUDE]** Dynamic snapshot |
| status | varchar(100) | **[EXCLUDE]** Dynamic snapshot |

---

## Table: encryptedPhoneNumbers **[EXCLUDE]**
**Reason**: Internal anonymization lookup table mapping raw phone numbers to HMAC-SHA256 hashes.

---

## Table: errorlogs **[EXCLUDE]**
**Reason**: Internal application error log.

---

## Table: exchangerates **[EXCLUDE]**
**Reason**: Better and more authoritative sources are available online (World Bank, IMF). Daily USD/KES and USD/NGN rates 2018–present.

---

## Table: gmgCustomers **[VIEW]**
## Table: gmgMeterReadings **[VIEW]**
## Table: gmgMiniGridProjects **[VIEW]**
## Table: gmgTariffs **[VIEW]**

---

## Table: meteringbasestations **[EXCLUDE]**
**Reason**: Internal operational data only; contains credentials (auth tokens, WiFi passwords, SIM cards, IP addresses). The scientifically relevant fields (timezone offset, metering platform, site status) are derivable from `meteringplatformtariffs` and `minigridprojects`.

---

## Table: meteringplatformcustomers **[EXCLUDE]**
**Reason**: Currently empty (0 rows).

---

## Table: meteringplatformtariffs
**Purpose**: Tariff definitions as returned by the metering platform API.

| Column | Type | Description |
|--------|------|-------------|
| id | int unsigned PK | Auto-increment row ID |
| meteringBaseStation | varchar(300) | Associated base station |
| name | varchar(300) | Tariff name |
| totalRate | decimal(10,2) | Total tariff rate (local currency per kWh) |

---

## Table: minigridprojects
**Purpose**: Mini-grid project specifications. One row per site. 26 rows total (23 real + 3 test placeholders that will be excluded from release).

| Column | Type | Release |
|--------|------|---------|
| projectName | varchar(45) PK | Unique project/community name |
| country | varchar(45) | Project country (Kenya or Nigeria) |
| company | varchar(100) | Operating company |
| language | varchar(45) | Primary language at the site |
| currency | varchar(45) | Local currency |
| timezoneOffsetUtc | int | UTC offset in hours (Kenya=3, Nigeria=1) |
| lat | decimal(20,10) | Site latitude (community-level) |
| long | decimal(20,10) | Site longitude (community-level) |
| meteringProjectId | varchar(100) | Project ID in the metering platform |
| sizePv | decimal(7,3) | Installed solar PV capacity (kWp) |
| sizeBattery | decimal(7,3) | Battery storage capacity (kWh) |
| typeBattery | varchar(45) | Battery chemistry (e.g., lead-acid, Li-ion) |
| voltageSinglePhase | int | Single-phase grid voltage (V) |
| phaseCount | int | Number of electrical phases |
| capex | decimal(11,2) | Capital expenditure (local currency) |
| pvwattsDataSource | varchar(45) | **[EXCLUDE]** Downloaded from NREL PVWatts |
| pvwattsProductionAnnual | decimal(6,2) | **[EXCLUDE]** Downloaded from NREL PVWatts |
| pvwattsMonthlyAveragekWhProduced | decimal(8,2) | **[EXCLUDE]** Downloaded from NREL PVWatts |
| investors | varchar(45) | **[EXCLUDE]** No scientific value |
| donors | varchar(45) | **[EXCLUDE]** No scientific value |
| powerOnDate | date | System commissioning date |
| powerSoldDate | date | Date first electricity was sold to customers (NULL if not yet sold) |
| generationType | varchar(50) | Generation technology (PV Solar for all real sites) |
| peakLoadCapacity | decimal(10,2) | Peak load capacity (kVA) |
| solarPanelSupplier | varchar(100) | Solar panel manufacturer |
| solarPanelsCount | int | Number of solar panels installed |
| inverterSupplier | varchar(100) | Inverter manufacturer |
| inverterModel | varchar(100) | Inverter model |
| invertersCount | int | Number of inverters |
| batterySupplier | varchar(100) | Battery manufacturer |
| batteryBanks | int | Number of battery units |
| dieselPowerOutputkva | decimal(10,2) | Diesel generator capacity (kVA); 0 if no generator |
| dataCollectionSystems | varchar(100) | Data collection systems in use |
| remoteMonitoringPlatform | varchar(255) | **[EXCLUDE]** IUO |
| remoteMonitoringSiteId | int | **[EXCLUDE]** IUO |
| remoteMonitoringUrl | varchar(255) | **[EXCLUDE]** IUO |
| remoteMonitoringAPIToken | varchar(255) | **[EXCLUDE]** Credential |

---

## Table: newsteamacocustomers **[EXCLUDE]**
**Reason**: Internal SteamaCo platform migration table.

---

## Table: paymentconfirmations
**Purpose**: Payment confirmations after the metering platform has processed a payment. ~1.03 million rows. Complements `paymentvalidations`.

**Data quality notes**:
- `paymentProcessor` has inconsistent casing — normalize to lowercase ("mpesa", "paga")
- `transactionDatetime` is `0000-00-00` or NULL for ~4,700 early M-PESA records where no date was transmitted; time-of-day may still be valid
- ~5 records have year=1 or year=2 — date parsing errors; flag these

| Column | Type | Release |
|--------|------|---------|
| id | int PK | Auto-increment row ID |
| paymentProcessor | varchar(45) | Payment processor name (normalize to lowercase: mpesa, paga) |
| processorTransactionType | varchar(45) | Transaction type as reported by the processor |
| transactionChannel | varchar(45) | Payment channel (e.g., mobile, USSD) |
| businessShortCode | varchar(45) | **[EXCLUDE]** IUO |
| transactionID | varchar(100) | **[EXCLUDE]** IUO |
| transactionDatetime | datetime | Date and time of transaction (some records have 0000-00-00 date — see note) |
| currency | varchar(45) | Transaction currency (KES or NGN) |
| amount | decimal(12,2) | Payment amount in local currency |
| renewviaAmount | decimal(12,2) | Amount credited to Renewvia after fees |
| isCredit | tinyint | 1 if this credits the customer's meter account |
| isProcessorTest | tinyint | 1 if this is a test transaction from the payment processor |
| invoiceNumber | varchar(100) | **[EXCLUDE]** IUO |
| thirdPartyTransactionID | varchar(100) | **[EXCLUDE]** IUO |
| renewviaBalance | decimal(12,2) | Renewvia account balance after this transaction |
| customerAccountNumber | varchar(45) | **[PSEUDONYMIZE]** Customer account number |
| phoneNumber | varchar(45) | **[EXCLUDE]** PII |
| firstName | varchar(45) | **[EXCLUDE]** PII |
| middleName | varchar(45) | **[EXCLUDE]** PII |
| lastName | varchar(45) | **[EXCLUDE]** PII |
| country | varchar(45) | Country (Kenya or Nigeria) |
| meterPlatform | varchar(45) | Metering platform that processed the credit |
| meteringResponse | varchar(45) | Response code from the metering platform |
| meteringTransactionID | varchar(100) | Transaction ID assigned by the metering platform |
| standardSiteCode | varchar(45) | Site code |
| projectName | varchar(45) FK→minigridprojects | Mini-grid project |
| renewviaResponse | varchar(45) | Renewvia internal processing response |
| isTest | tinyint | 1 if this is an internal test payment |
| isSignup | tinyint | 1 if this is the customer's initial signup payment |
| isBalanceTransfer | tinyint | 1 if this is a balance transfer between accounts |
| isAutomatic | tinyint | 1 if this payment was initiated automatically |
| isReversed | tinyint(1) | 1 if this payment was subsequently reversed |

---

## Table: paymentreceiptsqueue **[EXCLUDE]**
**Reason**: Empty (0 rows).

---

## Table: paymentvalidations
**Purpose**: Initial payment validation records from the payment processor webhook, before metering platform processing. ~1.51 million rows. Same schema as `paymentconfirmations` except no `isReversed` or `meteringTransactionID` columns.

**Data quality notes**: Same as `paymentconfirmations`.

| Column | Type | Release |
|--------|------|---------|
| id | int PK | Auto-increment row ID |
| paymentProcessor | varchar(45) | Payment processor name (normalize to lowercase) |
| processorTransactionType | varchar(45) | Transaction type as reported by the processor |
| transactionChannel | varchar(45) | Payment channel |
| businessShortCode | varchar(45) | **[EXCLUDE]** IUO |
| transactionID | varchar(100) | **[EXCLUDE]** IUO |
| transactionDatetime | datetime | Date and time of transaction (some records have 0000-00-00 date) |
| currency | varchar(45) | Transaction currency |
| amount | decimal(12,2) | Payment amount in local currency |
| renewviaAmount | decimal(12,2) | Amount credited to Renewvia after fees |
| isCredit | tinyint | 1 if this is a credit |
| isProcessorTest | tinyint | 1 if this is a test transaction |
| invoiceNumber | varchar(100) | **[EXCLUDE]** IUO |
| thirdPartyTransactionID | varchar(100) | **[EXCLUDE]** IUO |
| renewviaBalance | decimal(12,2) | Renewvia account balance after this transaction |
| customerAccountNumber | varchar(45) | **[PSEUDONYMIZE]** Customer account number |
| phoneNumber | varchar(45) | **[EXCLUDE]** PII |
| firstName | varchar(45) | **[EXCLUDE]** PII |
| middleName | varchar(45) | **[EXCLUDE]** PII |
| lastName | varchar(45) | **[EXCLUDE]** PII |
| country | varchar(45) | Country |
| meterPlatform | varchar(45) | Metering platform |
| meteringResponse | varchar(45) | Response code from metering platform |
| standardSiteCode | varchar(45) | Site code |
| projectName | varchar(45) FK→minigridprojects | Mini-grid project |
| renewviaResponse | varchar(45) | Renewvia internal processing response |
| isTest | tinyint | 1 if this is an internal test payment |
| isSignup | tinyint | 1 if this is a signup payment |
| isBalanceTransfer | tinyint | 1 if this is a balance transfer |
| isAutomatic | tinyint | 1 if this payment was initiated automatically |

---

## Table: poles **[EXCLUDE]**
**Reason**: Internal use only.

---

## Table: poles_v2 **[EXCLUDE]**
**Reason**: Internal use only.

---

## Table: smsSurveys **[EXCLUDE]**
**Reason**: Internal use only.

---

## Table: sparkmetercustomers
**Purpose**: Customer snapshot from the SparkMeter platform API. 8,955 rows.

| Column | Type | Release |
|--------|------|---------|
| rowId | int unsigned PK | Auto-increment row ID |
| code | varchar(100) | Customer code on the SparkMeter platform |
| creditBalance | decimal(10,3) | Current credit balance |
| debtBalance | decimal(10,3) | Current debt balance |
| ground_id | varchar(100) | SparkMeter ground/site ID |
| ground_name | varchar(100) | SparkMeter ground/site name |
| id | varchar(100) | **[PSEUDONYMIZE]** SparkMeter customer UUID |
| meters_active | tinyint | 1 if the meter is currently active |
| meters_address | varchar(100) | **[EXCLUDE]** Private |
| meters_bootloader | varchar(100) | Meter bootloader version |
| meters_city | varchar(100) | **[EXCLUDE]** Private |
| meters_coords | varchar(100) | **[EXCLUDE]** Private |
| meters_country | varchar(100) | **[EXCLUDE]** Private |
| meters_currentDailyEnergy | decimal(10,3) | Energy consumed today (kWh) |
| meters_currentTariffName | varchar(100) | Currently applied tariff name |
| meters_firmware | varchar(100) | Meter firmware version |
| meters_isRunningPlan | tinyint | 1 if the meter has an active prepaid plan |
| meters_lastConfigDatetime | varchar(100) | Timestamp of last configuration push |
| meters_lastCycleStart | varchar(100) | Start of most recent billing cycle |
| meters_lastEnergy | decimal(10,3) | Cumulative energy reading at last heartbeat (kWh) |
| meters_lastEnergyDatetime | varchar(100) | Timestamp of the last energy reading |
| meters_lastMeterStateCode | int | State code at last heartbeat (see SparkMeter docs) |
| meters_lastPlanExpirationDate | varchar(100) | Expiration date of current prepaid plan |
| meters_lastPlanPaymentDate | varchar(100) | Date of most recent plan payment |
| meters_model | varchar(100) | Meter hardware model |
| meters_operatingMode | int | Meter operating mode code |
| meters_planBalance | decimal(10,3) | Remaining prepaid plan balance |
| meters_postalCode | varchar(100) | Postal code |
| meters_serial | varchar(100) | Meter serial number |
| meters_state | varchar(100) | Meter state description (see SparkMeter docs) |
| meters_street1 | varchar(100) | **[EXCLUDE]** Private |
| meters_street2 | varchar(100) | **[EXCLUDE]** Private |
| meters_tags | varchar(1000) | **[EXCLUDE]** Private |
| meters_totalCycleEnergy | decimal(10,3) | Total energy consumed in current billing cycle (kWh) |
| name | varchar(100) | **[EXCLUDE]** PII |
| phoneNumber | varchar(100) | **[EXCLUDE]** PII |
| phoneNumberVerified | tinyint(1) | 1 if phone number has been verified |

---

## Table: sparkmeterreadings
**Purpose**: 15-minute heartbeat energy readings from SparkMeter meters. Core dataset. ~363 million rows.

**Energy field notes**: SparkMeter meters cannot confirm whether a heartbeat was received by the base station. To allow gap reconstruction, meters report both:
- `kilowattHours` — energy consumed **during this 15-minute heartbeat period** (kWh) — primary consumption metric
- `energy` — cumulative kWh consumed since last meter reset — used for gap detection and recovery

`kilowattHoursPeriod` is of unknown/unclear purpose and is dropped. `UncertainMetadata` is an internal flag with no analytic value and is dropped.

| Column | Type | Release |
|--------|------|---------|
| row_id | int PK | Auto-increment row ID |
| UncertainMetadata | tinyint | **[EXCLUDE]** Internal flag, no analytic value |
| type | varchar(45) | Record type (always "reading") |
| id | varchar(100) UNIQUE | SparkMeter-assigned reading UUID |
| organization | varchar(100) | Organization ID (unused in analysis) |
| site | varchar(100) | SparkMeter site identifier |
| heartbeatStart | datetime | Start of the 15-minute measurement period |
| heartbeatEnd | datetime | End of the 15-minute measurement period (heartbeatStart + 15 min) |
| energy | decimal(15,5) | Cumulative energy consumed since last meter reset (kWh) |
| kilowattHours | decimal(15,5) | Energy consumed during this heartbeat period (kWh) |
| kilowattHoursPeriod | decimal(15,5) | **[EXCLUDE]** Purpose unclear |
| rate | decimal(60,30) | Tariff rate at time of reading (local currency per kWh) |
| touModifier | decimal(10,5) | Time-of-use rate modifier (1.0 = no modification) |
| voltageMin | decimal(10,5) | Minimum voltage during the period (V) |
| voltageMax | decimal(10,5) | Maximum voltage during the period (V) |
| voltageAvg | decimal(10,5) | Average voltage during the period (V) |
| currentMin | decimal(10,5) | Minimum current during the period (A) |
| currentMax | decimal(10,5) | Maximum current during the period (A) |
| currentAvg | decimal(10,5) | Average current during the period (A) |
| apparentPowerAvg | decimal(15,5) | Average apparent power (VA) |
| powerFactorAvg | decimal(10,5) | Average power factor (0–1) |
| truePowerAvg | decimal(15,5) | Average true (active) power during the period (W) |
| truePowerInst | decimal(15,5) | Instantaneous true power at end of heartbeat period (W) |
| frequency | decimal(10,5) | AC frequency (Hz) |
| uptime | int | Device uptime since last reset (seconds) |
| readingId | varchar(100) | Alternate reading identifier |
| state | int | Meter state code (see https://get.support.sparkmeter.io/servicedesk/customer/portal/4/article/3240263726) |
| meter_id | varchar(100) | SparkMeter meter UUID |
| meter_modelName | varchar(100) | Meter hardware model |
| meter_serial | varchar(100) | Meter serial number |
| meter_code | varchar(100) | Meter code (usually matches customer code) |
| meter_tags | varchar(1000) | Tags applied to the meter |
| meter_type | varchar(100) | Meter role: `customer` (end-user), `totalizer` (site-level aggregation), `pue` (productive use equipment) |
| meter_address_street1 | varchar(100) | **[EXCLUDE]** PII |
| meter_address_street2 | varchar(100) | **[EXCLUDE]** PII |
| meter_address_city | varchar(100) | **[EXCLUDE]** PII |
| meter_address_postalcode | varchar(100) | **[EXCLUDE]** |
| meter_address_state | varchar(100) | **[EXCLUDE]** |
| meter_address_coords_lat | decimal(15,13) | Meter latitude (community-level) |
| meter_address_coords_lon | decimal(15,13) | Meter longitude (community-level) |
| meter_customer_id | varchar(100) | **[PSEUDONYMIZE]** Customer UUID |
| meter_customer_code | varchar(1000) | **[PSEUDONYMIZE]** Customer account code |
| meter_customer_code_backup | varchar(1000) | **[PSEUDONYMIZE]** Backup customer code |
| meter_customer_name | varchar(100) | **[EXCLUDE]** PII |
| meter_customer_phoneNumber | varchar(20) | **[EXCLUDE]** PII |
| meter_tariff_id | varchar(100) | Tariff UUID |
| meter_tariff_name | varchar(100) | Tariff name |
| userPowerLimit | decimal(13,5) | Per-user power limit (W) |

---

## Derived dataset: sparkmeterreadings_clean
**Source**: Generated from `sparkmeterreadings` by `clean_readings.py`. One parquet file per site (`data/sparkmeterreadings_clean/<site>.parquet`).

**Purpose**: Clean 15-minute per-slot energy time series. The raw `sparkmeterreadings` table records cumulative energy counters (`energy`) and per-heartbeat increments (`kilowattHours`), but meters frequently miss heartbeats, making the per-heartbeat column unreliable for multi-slot gaps. This dataset reconstructs the full time series by differencing the cumulative counter and redistributing gap energy proportionally using a customer-specific daily load profile.

**Processing steps**:
1. Sort readings by `heartbeatStart` per meter.
2. Diff the cumulative `energy` counter to get per-transition consumption.
3. Null transitions where `energy_diff < 0` (meter reset) or `state ≠ 1` at either endpoint (error/off/unknown state).
4. Build a 96-slot daily load profile from consecutive clean single-slot transitions.
5. For multi-slot gaps with a known total, redistribute energy proportionally using the load profile. Slots whose time-of-day bucket has no clean observations fall back to a uniform (constant) rate.
6. Null-diff transitions produce no output rows (absent from the clean series).

**Energy conservation**: The sum of `energy_kwh` in the output equals the sum of valid raw energy diffs to within 1 × 10⁻⁵ relative tolerance.

| Column | Type | Description |
|--------|------|-------------|
| meter_customer_code | string | **[PSEUDONYMIZE]** Customer account code (matches `sparkmeterreadings.meter_customer_code`) |
| meter_type | string | Meter role: `customer`, `totalizer`, or `pue` |
| slot_start | timestamp (UTC, ns) | UTC start of the 15-minute slot |
| energy_kwh | float64 | Energy consumed during this slot (kWh) |
| imputation_method | string | `observed`: direct single-slot meter reading; `profile`: redistributed from a multi-slot gap using the customer's daily load profile; `uniform`: redistributed from a multi-slot gap using a uniform rate (no profile data for this time-of-day slot) |

---

## Table: sparkmetertransactions
**Purpose**: Financial transactions from the SparkMeter platform (payments, reversals, balance transfers). ~1.35 million rows.

| Column | Type | Release |
|--------|------|---------|
| row_id | int PK | Auto-increment row ID |
| UncertainMetadata | tinyint | **[EXCLUDE]** Internal flag |
| Version | int | Record schema version |
| type | varchar(100) | Transaction record type |
| id | varchar(100) UNIQUE | SparkMeter transaction UUID |
| organization | varchar(100) | Organization ID |
| site | varchar(100) | Site identifier |
| acctType | varchar(100) | Account type (credit or debt) |
| transactionId | varchar(100) | Transaction identifier |
| userId | varchar(100) | User who initiated the transaction |
| referenceId | varchar(100) | **[EXCLUDE]** IUO |
| externalId | varchar(100) | **[EXCLUDE]** IUO |
| amount | decimal(30,15) | Transaction amount (local currency) |
| source | varchar(100) | Transaction source (cash, bonus, reversal, etc.) |
| state | varchar(100) | Transaction state (pending, processed, errored, reversed) |
| origin | varchar(100) | Transaction origin (user, system, reversal) |
| memo | varchar(1000) | **[EXCLUDE]** IUO |
| to_id | varchar(100) | Recipient meter/account UUID |
| to_address_street1 | varchar(100) | **[EXCLUDE]** PII |
| to_address_street2 | varchar(100) | **[EXCLUDE]** PII |
| to_address_city | varchar(100) | **[EXCLUDE]** PII |
| to_address_state | varchar(100) | **[EXCLUDE]** PII |
| to_address_postalcode | varchar(100) | **[EXCLUDE]** |
| to_address_coords_lat | varchar(100) | Recipient latitude (community-level) |
| to_address_coords_lon | varchar(100) | Recipient longitude (community-level) |
| to_code | varchar(100) | Recipient meter code |
| to_modelName | varchar(100) | Recipient meter model |
| to_serial | varchar(100) | Recipient meter serial |
| to_tags | varchar(100) | Recipient meter tags |
| to_type | varchar(100) | Recipient entity type |
| to_customer_id | varchar(100) | **[PSEUDONYMIZE]** Recipient customer UUID |
| to_customer_name | varchar(100) | **[EXCLUDE]** PII |
| to_customer_code | varchar(1000) | **[PSEUDONYMIZE]** Recipient customer code |
| to_customer_code_backup | varchar(1000) | **[PSEUDONYMIZE]** Recipient backup code |
| to_customer_phoneNumber | varchar(100) | **[EXCLUDE]** PII |
| to_tariff_id | varchar(100) | Recipient tariff UUID |
| to_tariff_name | varchar(100) | Recipient tariff name |
| to_walletType | varchar(100) | Recipient wallet type (credit or debt) |
| to_name | varchar(100) | **[EXCLUDE]** Private |
| to_isSystemAccount | varchar(100) | Whether recipient is a system account |
| from_id | varchar(100) | Sender meter/account UUID |
| from_address_street1 | varchar(100) | **[EXCLUDE]** PII |
| from_address_street2 | varchar(100) | **[EXCLUDE]** PII |
| from_address_city | varchar(100) | **[EXCLUDE]** PII |
| from_address_state | varchar(100) | **[EXCLUDE]** PII |
| from_address_postalcode | varchar(100) | **[EXCLUDE]** |
| from_address_coords_lat | varchar(100) | Sender latitude (community-level) |
| from_address_coords_lon | varchar(100) | Sender longitude (community-level) |
| from_code | varchar(100) | Sender meter code |
| from_modelName | varchar(100) | Sender meter model |
| from_serial | varchar(100) | Sender meter serial |
| from_tags | varchar(100) | Sender meter tags |
| from_type | varchar(100) | Sender entity type |
| from_customer_id | varchar(100) | **[PSEUDONYMIZE]** Sender customer UUID |
| from_customer_name | varchar(100) | **[EXCLUDE]** PII |
| from_customer_code | varchar(1000) | **[PSEUDONYMIZE]** Sender customer code |
| from_customer_phoneNumber | varchar(100) | **[EXCLUDE]** PII |
| from_tariff_id | varchar(100) | Sender tariff UUID |
| from_tariff_name | varchar(100) | Sender tariff name |
| from_walletType | varchar(100) | Sender wallet type |
| from_name | varchar(100) | **[EXCLUDE]** Private |
| from_isSystemAccount | varchar(100) | Whether sender is a system account (1, 0, or NULL) |
| error | varchar(100) | Error message if transaction failed |
| created | datetime | Transaction creation timestamp |
| processedTimestamp | datetime | Timestamp when transaction was processed |
| reversedTimestamp | datetime | Timestamp when transaction was reversed (NULL if not reversed) |
| erroredTimestamp | datetime | Timestamp when transaction errored (NULL if no error) |

---

## Table: synota **[VIEW]**
## Table: uniMeteringPlatformCustomers **[VIEW]**
## Table: uniMiniGridProjects **[VIEW]**
## Table: uniSparkMeterReadings **[VIEW]**

---

## Table: tariffs
**Purpose**: Historical tariff rate schedule. One row per tariff name per base station per effective date. 870 rows.

**Note**: Many early rows have `baseRate = 0` and `totalRate = 0` — placeholder rows created at system setup before rates were configured.

| Column | Type | Description |
|--------|------|-------------|
| rowId | int PK | Auto-increment row ID |
| meteringBaseStation | varchar(100) FK→meteringbasestations | Base station this tariff applies to |
| name | varchar(100) | Tariff name (e.g., Residential, Commercial) |
| tariffId | varchar(100) | Platform-assigned tariff identifier |
| startingDatetime | datetime | Date/time this rate took effect |
| baseRate | decimal(6,2) | Base electricity rate (local currency per kWh) |
| fuelAdder | decimal(6,2) | Fuel cost adjustment (local currency per kWh) |
| forexRate | decimal(5,4) | Foreign exchange adjustment factor |
| vatRate | decimal(3,3) | VAT/tax rate (fraction, e.g., 0.16 for 16%) |
| totalRate | decimal(6,2) | Total effective rate (local currency per kWh) |
| netPercentage | decimal(4,4) | Net percentage factor applied to the rate |

---

## Table: testingsandbox **[EXCLUDE]**
**Reason**: Empty (0 rows); schema copy for Victron VRM testing.

---

## Table: vrmgeneration
**Purpose**: Victron Energy Remote Monitoring (VRM) system telemetry. ~1-minute resolution. 3.68 million rows covering 16 community mini-grid sites, August 2023 – December 2024.

**Release note**: Rows for "UBA Acme, Ogba, Lagos, Nigeria" and "Shell Oza 1" (commercial/industrial clients, not community mini-grids) are excluded from the release. The 3 test-placeholder projects (lat/long = 0,0) are also excluded.

**Column note**: `Solar_Charger_N_*` columns exist for N = 0–9; columns for chargers not installed at a given site will be NULL. Some columns use `varchar(50)` where `decimal` would be expected due to mixed hardware configurations — notably `PV_Inverter_32_L1/L2/L3_Power` and some `Grid_L*` columns.

| Column | Type | Description |
|--------|------|-------------|
| row_id | int PK | Auto-increment row ID |
| timestamp_local | datetime | Measurement timestamp in site-local time |
| Project_Name | varchar(50) FK→minigridprojects | Mini-grid project name |
| Battery_Monitor_Cell_Imbalance_alarm | varchar(50) | Battery cell imbalance alarm state |
| Battery_Monitor_Current | decimal(10,5) | Battery current (A; positive=charging, negative=discharging) |
| Battery_Monitor_High_battery_temperature_alarm | varchar(50) | High battery temperature alarm state |
| Battery_Monitor_High_charge_current_alarm | varchar(50) | High charge current alarm state |
| Battery_Monitor_High_charge_temperature_alarm | varchar(50) | High charge temperature alarm state |
| Battery_Monitor_High_discharge_current_alarm | varchar(50) | High discharge current alarm state |
| Battery_Monitor_High_voltage_alarm | varchar(50) | High battery voltage alarm state |
| Battery_Monitor_Internal_Failure | varchar(50) | Battery monitor internal failure flag |
| Battery_Monitor_Low_battery_temperature_alarm | varchar(50) | Low battery temperature alarm state |
| Battery_Monitor_Low_charge_temperature_alarm | varchar(50) | Low charge temperature alarm state |
| Battery_Monitor_Low_voltage_alarm | varchar(50) | Low battery voltage alarm state |
| Battery_Monitor_Maximum_cell_voltage | decimal(10,5) | Maximum cell voltage in battery bank (V) |
| Battery_Monitor_Minimum_cell_voltage | decimal(10,5) | Minimum cell voltage in battery bank (V) |
| Battery_Monitor_State_of_charge | decimal(10,5) | Battery state of charge (%) |
| Battery_Monitor_Voltage | decimal(10,5) | Battery bank voltage (V) |
| Gateway_Dynamic_ESS_error_code | varchar(50) | Dynamic ESS error code from the VRM gateway |
| Generator_start_stop_Generator_not_detected_at_AC_input | varchar(50) | Generator detection alarm |
| Generator_start_stop_Generator_state | varchar(50) | Generator run state (Running, Stopped, etc.) |
| Generator_start_stop_Service_due | varchar(50) | Generator service due flag |
| PV_Inverter_20_Error | decimal(10,5) | PV inverter 20 error code |
| PV_Inverter_20_L1_Current | decimal(10,5) | PV inverter 20 phase 1 current (A) |
| PV_Inverter_20_L1_Power | decimal(10,5) | PV inverter 20 phase 1 power (W) |
| PV_Inverter_20_L1_Voltage | decimal(10,5) | PV inverter 20 phase 1 voltage (V) |
| PV_Inverter_20_L2_Current | decimal(10,5) | PV inverter 20 phase 2 current (A) |
| PV_Inverter_20_L2_Power | decimal(10,5) | PV inverter 20 phase 2 power (W) |
| PV_Inverter_20_L2_Voltage | decimal(10,5) | PV inverter 20 phase 2 voltage (V) |
| PV_Inverter_20_L3_Current | decimal(10,5) | PV inverter 20 phase 3 current (A) |
| PV_Inverter_20_L3_Power | decimal(10,5) | PV inverter 20 phase 3 power (W) |
| PV_Inverter_20_L3_Voltage | decimal(10,5) | PV inverter 20 phase 3 voltage (V) |
| PV_Inverter_20_Status | decimal(10,5) | PV inverter 20 status code |
| PV_Inverter_21_Error | varchar(50) | PV inverter 21 error code |
| PV_Inverter_21_L1_Current | decimal(10,5) | PV inverter 21 phase 1 current (A) |
| PV_Inverter_21_L1_Power | decimal(10,5) | PV inverter 21 phase 1 power (W) |
| PV_Inverter_21_L1_Voltage | decimal(10,5) | PV inverter 21 phase 1 voltage (V) |
| PV_Inverter_21_L2_Current | decimal(10,5) | PV inverter 21 phase 2 current (A) |
| PV_Inverter_21_L2_Power | decimal(10,5) | PV inverter 21 phase 2 power (W) |
| PV_Inverter_21_L2_Voltage | decimal(10,5) | PV inverter 21 phase 2 voltage (V) |
| PV_Inverter_21_L3_Current | decimal(10,5) | PV inverter 21 phase 3 current (A) |
| PV_Inverter_21_L3_Power | decimal(10,5) | PV inverter 21 phase 3 power (W) |
| PV_Inverter_21_L3_Voltage | decimal(10,5) | PV inverter 21 phase 3 voltage (V) |
| PV_Inverter_21_Status | varchar(50) | PV inverter 21 status |
| PV_Inverter_32_Error | decimal(10,5) | PV inverter 32 error code |
| PV_Inverter_32_L1_Current | decimal(10,5) | PV inverter 32 phase 1 current (A) |
| PV_Inverter_32_L1_Power | varchar(50) | PV inverter 32 phase 1 power (W; varchar due to mixed device data) |
| PV_Inverter_32_L1_Voltage | decimal(10,5) | PV inverter 32 phase 1 voltage (V) |
| PV_Inverter_32_L2_Current | decimal(10,5) | PV inverter 32 phase 2 current (A) |
| PV_Inverter_32_L2_Power | varchar(50) | PV inverter 32 phase 2 power (W; varchar due to mixed device data) |
| PV_Inverter_32_L2_Voltage | decimal(10,5) | PV inverter 32 phase 2 voltage (V) |
| PV_Inverter_32_L3_Current | decimal(10,5) | PV inverter 32 phase 3 current (A) |
| PV_Inverter_32_L3_Power | varchar(50) | PV inverter 32 phase 3 power (W; varchar due to mixed device data) |
| PV_Inverter_32_L3_Voltage | decimal(10,5) | PV inverter 32 phase 3 voltage (V) |
| Solar_Charger_N_Battery_temperature | decimal(10,5) | Battery temperature at solar charger N (°C) |
| Solar_Charger_N_Battery_watts | decimal(10,5) | Power delivered to battery by solar charger N (W) |
| Solar_Charger_N_Current | decimal(10,5) | Battery charge current from solar charger N (A) |
| Solar_Charger_N_Error_code | varchar(50) | Solar charger N error code |
| Solar_Charger_N_PV_current | decimal(10,5) | PV array current into solar charger N (A) |
| Solar_Charger_N_PV_power | decimal(10,5) | PV array power into solar charger N (W) |
| Solar_Charger_N_PV_voltage | decimal(10,5) | PV array voltage at solar charger N (V) |
| Solar_Charger_N_Voltage | decimal(10,5) | Battery voltage at solar charger N (V) |
| Solar_Charger_8_Relay_on_the_charger | varchar(50) | Relay state on solar charger 8 |
| System_overview_AC_Consumption_L1 | decimal(10,5) | Total AC load on phase 1 (W) |
| System_overview_AC_Consumption_L2 | decimal(10,5) | Total AC load on phase 2 (W) |
| System_overview_AC_Consumption_L3 | decimal(10,5) | Total AC load on phase 3 (W) |
| System_overview_AC_Input | varchar(50) | AC input source description |
| System_overview_Battery_Power | decimal(10,5) | Net battery power (W; positive=charging) |
| System_overview_Battery_SOC | decimal(10,5) | Battery state of charge (%) |
| System_overview_Battery_state | varchar(50) | Battery state (Charging, Discharging, Idle) |
| System_overview_Current | decimal(10,5) | System DC current (A) |
| System_overview_DVCC_Multiple_batteries_alarm | varchar(50) | DVCC multiple batteries alarm |
| System_overview_Genset_L1 | decimal(10,5) | Generator power phase 1 (W) |
| System_overview_Genset_L2 | decimal(10,5) | Generator power phase 2 (W) |
| System_overview_Genset_L3 | decimal(10,5) | Generator power phase 3 (W) |
| System_overview_Grid_L1 | varchar(50) | Grid power phase 1 (W; varchar on some devices) |
| System_overview_Grid_L2 | varchar(50) | Grid power phase 2 (W; varchar on some devices) |
| System_overview_Grid_L3 | decimal(10,5) | Grid power phase 3 (W) |
| System_overview_Grid_alarm | varchar(50) | Grid alarm state |
| System_overview_No_grid_meter_alarm | varchar(50) | No grid meter detected alarm |
| System_overview_VE_Bus_charge_current | decimal(10,5) | VE.Bus inverter/charger charge current (A) |
| System_overview_VE_Bus_charge_power | decimal(10,5) | VE.Bus inverter/charger charge power (W) |
| System_overview_Voltage | decimal(10,5) | System DC voltage (V) |
| VE_Bus_System_VE_Bus_State | varchar(45) | VE.Bus inverter state (Inverting, Charging, Passthrough, etc.) |
| VE_Bus_System_High_DC_Ripple | varchar(50) | High DC ripple alarm |
| VE_Bus_System_Low_battery | varchar(50) | Low battery alarm |
| VE_Bus_System_Output_frequency | decimal(10,5) | AC output frequency (Hz) |
| VE_Bus_System_Overload | varchar(50) | Overload alarm |
| VE_Bus_System_Phase_rotation | varchar(50) | Phase rotation alarm |
| VE_Bus_System_Temperatur_sensor_alarm | varchar(50) | Temperature sensor alarm (note: column name has typo) |
| VE_Bus_System_Temperature | varchar(50) | VE.Bus temperature |
| VE_Bus_System_Voltage_sensor_alarm | varchar(50) | Voltage sensor alarm |
