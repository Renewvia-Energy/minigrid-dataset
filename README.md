# Renewvia Mini-Grid Dataset
This dataset contains operational records from 23 community solar mini-grids operated by Renewvia Energy in Kenya and Nigeria (2018–2025). It includes hundreds of millions of 15-minute meter readings from thousands of customers, along with payment transactions, tariff histories, site generation telemetry, and project metadata. Customer identifiers are pseudonymized via SHA-256 and all PII has been removed; the cross-table pseudonymization key allows consistent linkage between meter readings, payments, and customer demographics across the full seven-year span.

The dataset is the first of its kind for African solar mini-grids and is designed to support research in energy access, demand characterization, and mini-grid economics. Possible applications include load profile analysis (residential vs. productive-use customers), tariff and revenue modeling, grid reliability and meter-uptime studies, carbon accounting, and comparison of consumption behavior across diverse community types.

## I'm a collaborator. What should I do?
After signing and returning the DTUA to Nick, you'll get a link to a SPO directory, `data/`, containing the parquet files that make up the dataset. Move that folder into the parent directory of this repository, ensuring that the directory structure matches the map, below.

Before you get started, I strongly recommend you read the [Data Dictionary](./Data%20Dictionary.md) to understand what is in the parquet files. Personally, I think the `paymentvalidations` and `sparkmeterreadings_clean` tables are the richest.

You can safely ignore `explore/`, `scripts/`, `.env.example`, and `notes.md`. Those are for internal use to help Renewvia staff download the tables from our MySQL database into the parquet files contained in `data/`.

Scripts to generate visualizations should be kept in the `figures/` directory. Use the scripts in that folder to understand how to access and use the dataset. To run them, you'll first need to run `pip install -r requirements.txt`.

__To submit writing for the paper:__ We're targeting *Nature Scientific Data* for the submission of our data descriptor. *Sci. Data's* [submission guidelines](https://www.nature.com/sdata/submission-guidelines) not-so-subtly discourage LaTeX in favor of Microsoft Word, so if you need to access the draft directly, reach out to Nick for the SPO link.

__To submit figures__ or scripts to generate figures for the "Data Overview" and "Technical Validation" sections:
1. [Fork this repository](https://docs.github.com/en/pull-requests/how-tos/work-with-forks/fork-a-repo) to your own account.
2. [Clone](https://git-scm.com/docs/git-clone) your new fork to your personal computer.
3. Add your code to generate the figure to the `figures/` directory. Note that your script should assume the data from which to generate the figure will be in the `data/` directory (see the [directory map](https://github.com/Renewvia-Energy/minigrid-dataset/tree/main#directory-map), above). Use relative links in your script instead of absolute ones, and add any additional libraries used to `requirements.txt`; the script should work on any Ubuntu machine. Please document thoroughly.
4. [Add](https://git-scm.com/docs/git-add), [commit](https://github.com/git-guides/git-commit), and [push](https://git-scm.com/docs/git-push) your new files to your GitHub repository online.
5. Submit a [pull request](https://docs.github.com/en/pull-requests/reference/pull-requests) from your fork to this main repository. Nick will review it in due course.

If you are not comfortable enough with git to confidently follow the above instructions, fear not! Just email your figure generation code to Nick, and he'll take care of the rest.

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