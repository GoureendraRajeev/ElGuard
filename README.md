# ElGuard: El Niño temperature outlook and climate data explorer for South India

ElGuard forecasts the **monthly average daily high and low temperature** for all **83 districts** of Kerala, Karnataka and Tamil Nadu, and lets you explore the **real measured climate data** of any district and year (1985 onwards) on an interactive website.

> Student project. It is not an official forecast.

## What it does

- **Forecast.** For every district and each month of 2027 (and the rest of 2026), the expected average daily high and low in °C, with a likely range.
- **Climate data explorer.** Pick a district (or click it on its state map) and a year to see monthly rainfall, daily highs and lows, monsoon rainfall, and the El Niño and Indian Ocean Dipole index values.
- **Three separate state maps** with every district named, drawn from district boundaries (no map service or API key needed).
- **Live temperature** of the chosen district (Open-Meteo, no key).

## How the forecast works

1. Each district gets its own **warming trend** for every calendar month (a straight line through its past years).
2. A small **Ridge regression** adds an **El Niño adjustment**, learned from the El Niño index known at forecast time and its change over the last 3 months. The lead time differs for each month, so each month has its own test and model.
3. **Test:** leave-one-year-out. Every year from 1985 to 2025 is predicted by a model that never saw that year.
4. **Rule decided in advance:** the El Niño adjustment is used for a month only if it lowers the squared error by at least 10% compared with the trend alone; otherwise that month uses the trend alone.
5. The shaded range comes from the model's own past errors (10% to 90%).

### Tested error (RMSE in °C)

| Month | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Daily high | 0.56 | 0.56 | 0.63 | 0.80 | 1.05 | 0.89 | 0.72 | 0.65 | 0.69 | 0.70 | 0.66 | 0.63 |
| Daily low | 0.80 | 0.75 | 0.65 | 0.53 | 0.53 | 0.47 | 0.37 | 0.35 | 0.34 | 0.42 | 0.67 | 0.89 |

El Niño improved the forecast for **February to April (highs)** and **February to May (lows)**. The other months use each district's warming trend.

### Findings

- After an **El Niño winter**, high spring heat covered about 41% of district-years, against about 20% after neutral winters and 6% after La Niña winters.
- **Rainfall could not be predicted with useful skill.** Monthly and seasonal models, with and without the Indian Ocean Dipole, did not pass the tests, because El Niño's rainfall effect differs by state and year. The experiments are kept in `pipeline/experiments`.

## Limitations

- The forecast is **provisional**: it assumes the El Niño index stays at its latest value, and gets firmer as new data arrives.
- It forecasts **monthly averages**, not daily weather, and not rainfall, floods or heatwave days.
- Only about 40 independent years stand behind the tests, and neighbouring districts move together.
- Values are district averages of a coarse data grid (the temperature grid is about 1 degree), not weather-station readings.


## Data sources

| Data | Source |
|---|---|
| Temperature and rainfall, 1985 to 2025 | IMD gridded data (via the `imdlib` package) |
| Recent months and live temperature | Open-Meteo |
| El Niño index (ONI) | NOAA CPC |
| Indian Ocean Dipole (DMI) | NOAA PSL |
| District boundaries | Esri India, 2024 |

Please check each source's terms before reusing the data. The raw IMD files are not stored in this repository.

## Project structure

```
config/             settings for each state
data/geojson/       district boundaries
data/processed/     monthly district data and forecasts (small CSV files)
models/             test results (JSON)
pipeline/           the data and forecast scripts
pipeline/experiments/   earlier attempts (rainfall and heat-risk models)
site/data/          the data the website reads
webapp/             the Django website
```

## How to run

Python 3.10 or newer.

```
python -m venv .venv
.venv\Scripts\activate            (Mac or Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

**Run the website straight away** (the prepared data is in `site/data`):

```
cd webapp
python manage.py runserver
```

Open http://127.0.0.1:8000.

**Rebuild everything from the sources**, from the project folder, in this order:

```
python pipeline/download_oni.py
python pipeline/download_dmi.py
python pipeline/download_districts.py
python pipeline/download_imd.py --start 1985 --end 2025
python pipeline/aggregate.py --start 1985 --end 2025
python pipeline/download_recent.py
python pipeline/forecast_2027.py
python pipeline/export_site_data.py
```

The IMD download is large and slow. `download_recent.py` waits and retries if Open-Meteo says "too many requests".


