# Bus Map Generator
This script will automatically generate a bus map of the UK

## How to use this script
First, install the required dependincies:
`pip install pygame colorama requests beautifulsoup4`

You can just run the script as is and it will prompt you to download the data needed to generate a map, however this will take a while, especially to download the geometry data.
`python3 busmapgen.py`

Before running the script for the first time, I would recommend downloading the geometry data from [here](https://nextcloud.verumignis.com/index.php/s/FaHQJARTWecQjKn), then, extract the zip into the same directory as the script and set `UPDATE_GEOMETRY = True` the first time you run the script to download the geometry any new routes.

The first time you run the script it will download the route data from bustimes.org, this combines data from the API with data that has to be scraped from the website. Its not ideal and could be broken if bustimes.org changes the page structure, but it is the most accurate source of data.

The script will also download the cities and colors data from my website. If you want to make your own cities.csv, I would suggest using the OS open name data, although this does not cover ireland.
