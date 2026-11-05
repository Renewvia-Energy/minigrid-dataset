# Renewvia Mini-Grid Dataset
This is the operational repository for the Zenodo dataset "[High-Frequency, Multi-Domain Operational Dataset for Community Solar Mini-Grids in Kenya and Nigeria](https://doi.org/10.5281/zenodo.22149101)." The dataset contains operational records from 23 community solar mini-grids operated by Renewvia Energy in Kenya and Nigeria (2018–2025). It includes hundreds of millions of 15-minute meter readings from thousands of customers, along with payment transactions, tariff histories, site generation telemetry, and project metadata. Customer identifiers are pseudonymized via SHA-256 and all PII has been removed; the cross-table pseudonymization key allows consistent linkage between meter readings, payments, and customer demographics across the full seven-year span.

The dataset is the first of its kind for African solar mini-grids and is designed to support research in energy access, demand characterization, and mini-grid economics. Possible applications include load profile analysis (residential vs. productive-use customers), tariff and revenue modeling, grid reliability and meter-uptime studies, carbon accounting, and comparison of consumption behavior across diverse community types.

This crux of this repository are two subdirectories:
* `figures/` contains Python scripts to generate visuals using the data
* `scripts/` contains Python scripts I used to download, process, and export the data from Renewvia's private servers to Zenodo

## Quickstart
1. Clone this repository to your machine
2. Make a new, empty `data/` directory in your local copy of this repo
3. Download the dataset from [Zenodo](https://doi.org/10.5281/zenodo.22149101) into the `data/` directory
4. Run `pip install -r requirements.txt`
5. Start running scripts from `figures/` to generate visuals based on the data
6. Write your own scripts to investigate novel hypotheses based on the dataset!

## Citing
In October 2026, we submitted a data descriptor to *Nature Scientific Data*. When that gets published, we request you cite it. Until then, if this dataset has been significant in your research, and you would like to acknowledge the project in your academic publication, we suggest citing the following paper:
> Selby, N. (2026). High-Frequency, Multi-Domain Operational Dataset for Community Solar Mini-Grids in Kenya and Nigeria (Version 1.0) [Dataset]. Zenodo. https://doi.org/10.5281/zenodo.22149102

## Directory map

```
minigrid-dataset/
├── data/   # Published dataset. This is gitignored, so you'll need to download the dataset from https://doi.org/10.5281/zenodo.22149102
│   ├── customers.parquet
│   ├── meteringbasestations.parquet
│   ├── meteringplatformtariffs.parquet
│   ├── minigridprojects.parquet
│   ├── paymentconfirmations.parquet
│   ├── paymentvalidations.parquet
│   ├── sparkmetercustomers.parquet
│   ├── sparkmeterreadings_<site>.parquet        # One file per site, all years merged
│   ├── sparkmeterreadings_clean_<site>.parquet  # Cleaned 15-min energy time series
│   ├── sparkmetertransactions.parquet
│   ├── tariffs.parquet
│   └── vrmgeneration.parquet
├── figures/                            # Visualization scripts
│   ├── plot_load_profile.py            # Average daily load profiles by customer tier
│   ├── plot_arpu.py                    # Average revenue per user over time
│   ├── plot_acpu.py                    # Average cost per unit by site
│   ├── prep_acpu.py                    # Data prep for ACPU analysis
│   ├── plot_carbon_accounting.py       # Carbon offset estimates by site
│   ├── carbon_accounting.py            # Carbon accounting calculations
│   ├── plot_power_quality.py           # Voltage/frequency power quality metrics
│   └── power_quality.py                # Power quality data prep
├── scripts/                            # Data pipeline
│   ├── export.py                       # DB → Parquet (requires database access)
│   ├── clean_readings.py               # Raw readings → clean 15-min time series
│   ├── flatten.py                      # Reorganize data/ into flat layout for Zenodo upload
│   └── upload.py                       # Upload data/ files to Zenodo
├── paper/                              # LaTeX source files for data descriptor
├── explore/                            # Ad-hoc SQL analysis queries
│   └── *.sql
├── .env.example                        # Example .env file; IUO
├── .gitignore                          # Files not to be uploaded to GitHub
├── Data Dictionary.md                  # Column-level documentation for all tables
├── notes.md                            # Notes on data tables, quality, anonymization, ideas for analysis, etc.
├── requirements.txt                    # Python dependencies for figures/ and scripts/
└── README.md                           # This document
```