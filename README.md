# Renewvia Mini-Grid Dataset

This dataset contains operational records from 23 community solar mini-grids operated by Renewvia Energy in Kenya and Nigeria (2018–2025). It includes hundreds of millions of 15-minute meter readings from thousands of customers, along with payment transactions, tariff histories, site generation telemetry, and project metadata. Customer identifiers are pseudonymized via SHA-256 and all PII has been removed; the cross-table pseudonymization key allows consistent linkage between meter readings, payments, and customer demographics across the full seven-year span.

The dataset is the first of its kind for African solar mini-grids and is designed to support research in energy access, demand characterization, and mini-grid economics. Possible applications include load profile analysis (residential vs. productive-use customers), tariff and revenue modeling, grid reliability and meter-uptime studies, carbon accounting, and comparison of consumption behavior across diverse community types.

## I'm a collaborator. What should I do?
After signing and returning the DTUA to Nick, you'll get a link to a SPO directory, `data/`, containing the parquet files that make up the dataset. Move that folder into the parent directory of this repository, ensuring that the directory structure matches the map, below.

Before you get started, I strongly recommend you read the [Data Dictionary](./Data%20Dictionary.md) to understand what is in the parquet files. Personally, I think the `paymentvalidations` and `sparkmeterreadings_clean` tables are the richest.

You can safely ignore `explore/`, `scripts/`, `.env.example`, and `notes.md`. Those are for internal use to help Renewvia staff download the tables from our MySQL database into the parquet files contained in `data/`.

Scripts to generate visualizations should be kept in the `figures/` folder. Use the scripts in that folder to understand how to access and use the dataset. To run them, you'll first need to run `pip install -r requirements.txt`.

## Directory map

```
minigrid-dataset/
├── data/   # Published dataset. This is gitignored, so you'll need to download the dataset from Renewvia's SPO link after signing the DTUA.
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