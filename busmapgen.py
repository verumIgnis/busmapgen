try:
    import os, json, csv, sys, re, time
    import pygame, requests
    from math import cos, radians, sqrt
    from collections import defaultdict
    from colorama import init, Fore, Style
    from bs4 import BeautifulSoup
except ModuleNotFoundError:
    print("\033[31mOne or more dependencies are missing! To install required dependencies run:\033[0m") # cant use colorama because its not initialised yet
    print("pip install pygame colorama requests beautifulsoup4")

# ====== CONFIGURATION ======
# bounding box format: (lon, lat, lon, lat) - south west corner first
BOUNDING_BOX = (-10.8, 49.85, 2.1, 59.5)    # entire UK
#BOUNDING_BOX = (-2.6, 53.3, -2, 53.65)      # manchester
#BOUNDING_BOX = (-1.75, 53.65, -1.35, 54.0)  # leeds
#BOUNDING_BOX = (-0.6, 51.2, 0.4, 51.75)     # london
#BOUNDING_BOX = (-2.8, 51.35, -2.4, 51.6)    # bristol

scale_m_per_px = 350 # zoom - lower numbers result in higher quality outputs but take longer to render
MAX_LINE_LENGTH_METERS = 100000 # if one line exceeds this length, the entire route is omitted, avoids ugly lines from long distance coaches
WINDOW_TITLE = "Bus Map Generator"
BACKGROUND_COLOR = (20, 20, 20)

# this dosent really work because there is no reliable data as to what is and isnt a public route
IGNORE_PRIVATE_ROUTES = False
SHOW_ONLY_PRIVATE_ROUTES = False  # overrides IGNORE_PRIVATE_ROUTES if True

# filter by operator NOC or mode
EXCLUDE_OPERATORS = ["NATX", "RSTY", "PCCO", "GTSL", "REPS", "TCNT", "HNTC", "VOLN", "HADC", "CATS", "WINS", "OCNT", "SHCO"]  # Exclude operators, e.g. ["NATX", "RSTY", ""]
INCLUDE_OPERATORS = []  # Include only specified operators, e.g. ["METL"]; leave empty for no restriction

EXCLUDE_MODES = []  # Exclude modes, e.g. ["coach", "air", ""]
INCLUDE_MODES = []  # Include only specified modes; leave empty for no restriction

# calcuated as the distance from one corner of the bounding box to the opposite corner
MIN_ROUTE_LENGTH = 0              # meters
MAX_ROUTE_LENGTH = 10000000000    # meters

# frequency (buses per day, both directions), line width (px), brightness (0-255)
ROUTE_STYLE_BY_FREQUENCY = [
    [8, 1, 80],
    [20, 2, 124],
    [70, 2, 169],
    [120, 3, 212],
    [10000, 3, 255]
]

#labels
CITY_LABEL_COLOR = (255, 255, 255)
CITY_LABEL_ALPHA = 0 # 0 (invisible) to 255 (opaque)
CITY_LABEL_FONT_SIZE = 32
CITY_LABEL_FONT_NAME = None # None = system default
CITY_LABEL_UPPERCASE = True

# route labels
DRAW_ROUTE_LABELS = False
ROUTE_LABEL_FONT_NAME = None  # None = system default
ROUTE_LABEL_FONT_SIZE = 20
ROUTE_LABEL_ALPHA = 255
OVERRIDE_ROUTE_LABEL_COLOR = False # if false labels will be the same color as routes
ROUTE_LABEL_COLOR = (255, 255, 255)
ROUTE_LABEL_BG_COLOR = (15, 15, 15)
DRAW_ROUTE_LABEL_BOX = True
ROUTE_LABEL_BOX_WIDTH = 1
ROUTE_LABEL_BOX_PADDING = 3 # gap between text and box
ROUTE_LABEL_MAX_LENGTH = 8 # max characters

# data options
GEOMETRY_DIR = "geometry" # will be downloaded if missing from bustimes.org which takes a while, if you have slow internet ask verumIgnis for a copy, then update it with UPDATE_DATA
MAPS_DIR = "maps" # folder where the output will be saved
DATA_DIR = "data" # folder where the data CSVs are stored
ROUTES_CSV = "routes.csv" # will be downloaded from bustimes.org if missing which will take a while
CITIES_CSV = "cities.csv" # list of city names and locations - will be downloaded from verumignis.com if missing
OPERATOR_COLORS_CSV = "operator-colors.csv" # operator, r, g, b at max brightness - will be downloaded from verumignis.com if missing
UPDATE_ROUTES = False # updates route data, recomended to also update geometry or new routes will not display properly
UPDATE_GEOMETRY = False # updates geometry data to be up to date with routes data
UPDATE_DATA = False # updates cities CSV and colors CSV

# download options
SERVICES_SITEMAP_URL = "https://bustimes.org/sitemap-services.xml"
SERVICES_JSON_URL = "https://bustimes.org/api/services/?format=json&limit=1000000"
OPERATOR_COLORS_URL = "https://verumignis.com/operator-colors.csv"
CITIES_URL = "https://verumignis.com/cities.csv"
GEOMETRY_BASE_URL = "https://bustimes.org/services/{}.json"

HEADERS = { # will be included with any request made to any of the above URLs
    'User-Agent': 'Mozilla/5.0 (compatible; verumIgnis-busmap/1.0)'
}

PRIVATE_KEYWORDS = [ # used to determine if a route is private - if any of these strings appear on the route page on bustimes.org, the route is considered private
    "not open to the public",
    "For school students only."
]

# ===========================
# Below this line is the actual script. There are no config options below here, but feel free to edit it to add functionality.
# If you add anything cool, please send it to me (verumIgnis on discord), I would really like to see what you are able to do with this script.

ROUTES_CSV = os.path.join(DATA_DIR, ROUTES_CSV)
CITIES_CSV = os.path.join(DATA_DIR, CITIES_CSV)
OPERATOR_COLORS_CSV = os.path.join(DATA_DIR, OPERATOR_COLORS_CSV)

def meters_per_degree(lat):
    lat_rad = radians(lat)
    m_per_deg_lat = 111132.92 - 559.82 * cos(2 * lat_rad) + 1.175 * cos(4 * lat_rad)
    m_per_deg_lon = 111412.84 * cos(lat_rad) - 93.5 * cos(3 * lat_rad)
    return m_per_deg_lat, m_per_deg_lon

def geo_to_pixel(lon, lat, origin_lon, origin_lat, m_per_deg_lat, m_per_deg_lon):
    dx = (lon - origin_lon) * m_per_deg_lon
    dy = (origin_lat - lat) * m_per_deg_lat
    return int(dx / scale_m_per_px), int(dy / scale_m_per_px)

def bbox_intersects(bbox1, bbox2):
    min_lon1, min_lat1, max_lon1, max_lat1 = bbox1
    min_lon2, min_lat2, max_lon2, max_lat2 = bbox2
    return not (max_lon1 < min_lon2 or min_lon1 > max_lon2 or max_lat1 < min_lat2 or min_lat1 > max_lat2)

def segment_too_long(route, m_per_deg_lat, m_per_deg_lon):
    for segment in route:
        for i in range(len(segment) - 1):
            lon1, lat1 = segment[i]
            lon2, lat2 = segment[i + 1]
            dx = (lon2 - lon1) * m_per_deg_lon
            dy = (lat2 - lat1) * m_per_deg_lat
            dist = sqrt(dx * dx + dy * dy)
            if dist > MAX_LINE_LENGTH_METERS:
                return True
    return False

def bbox_diagonal_distance(bbox, m_per_deg_lat, m_per_deg_lon):
    min_lon, min_lat, max_lon, max_lat = bbox
    dx = (max_lon - min_lon) * m_per_deg_lon
    dy = (max_lat - min_lat) * m_per_deg_lat
    return sqrt(dx * dx + dy * dy)

def get_style_for_frequency(frequency):
    sorted_styles = sorted(ROUTE_STYLE_BY_FREQUENCY, key=lambda x: x[0])
    for threshold, width, color in sorted_styles:
        if frequency <= threshold:
            return width, color
    return sorted_styles[-1][1], sorted_styles[-1][2]

def get_operator_color(operator, operator_colors):
    return operator_colors.get(operator, operator_colors.get("DEFAULT", (255, 255, 255)))

def load_operator_colors(path):
    operator_colors = {}
    if not os.path.isfile(path):
        print(f"Warning: {path} not found, using fallback white.")
        return {"DEFAULT": (255, 255, 255)}
    with open(path, newline='', encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            try:
                op = row["operator"].strip()
                r = int(row["color_r"])
                g = int(row["color_g"])
                b = int(row["color_b"])
                operator_colors[op] = (r, g, b)
            except Exception as e:
                print(f"Error loading operator color for row {row}: {e}")
    if "DEFAULT" not in operator_colors:
        operator_colors["DEFAULT"] = (255, 255, 255)
    return operator_colors

def scale_color(color, target_brightness):
    r, g, b = color
    current_brightness = max(r, g, b)
    if current_brightness == 0:
        return (0, 0, 0)
    scale = target_brightness / current_brightness
    scaled = (
        min(255, int(r * scale)),
        min(255, int(g * scale)),
        min(255, int(b * scale))
    )
    return scaled

def draw_city_labels(screen, min_lon, max_lat, m_per_deg_lat, m_per_deg_lon):
    if not os.path.isfile(CITIES_CSV):
        print(f"{CITIES_CSV} not found!")
        return

    font = pygame.font.SysFont(CITY_LABEL_FONT_NAME, CITY_LABEL_FONT_SIZE)

    with open(CITIES_CSV, newline='', encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            try:
                name = row["name"]
                if CITY_LABEL_UPPERCASE:
                    name = name.upper()

                lon = float(row["longitude"])
                lat = float(row["latitude"])
                x, y = geo_to_pixel(lon, lat, min_lon, max_lat, m_per_deg_lat, m_per_deg_lon)

                label_surface = font.render(name, True, CITY_LABEL_COLOR)
                label_surface.set_alpha(CITY_LABEL_ALPHA)

                # center the label
                text_rect = label_surface.get_rect(center=(x, y))
                screen.blit(label_surface, text_rect)

            except Exception as e:
                print(f"Failed to render city {row.get('name', '?')}: {e}")

def draw_route_labels(screen, labels, m_per_deg_lat, m_per_deg_lon):
    if not DRAW_ROUTE_LABELS:
        return

    font = pygame.font.SysFont(ROUTE_LABEL_FONT_NAME, ROUTE_LABEL_FONT_SIZE)

    for label in labels:
        try:
            text = label["routeNumber"]
            points = label["points"]

            if OVERRIDE_ROUTE_LABEL_COLOR:
                color = ROUTE_LABEL_COLOR
            else:
                color = label["color"]

            if len(points) < 2:
                continue

            if len(text) > ROUTE_LABEL_MAX_LENGTH or text == "":
                continue

            distances = [0]
            for i in range(1, len(points)):
                x1, y1 = points[i-1]
                x2, y2 = points[i]
                dist = sqrt((x2 - x1)**2 + (y2 - y1)**2)
                distances.append(distances[-1] + dist)

            total_dist = distances[-1]
            if total_dist == 0:
                continue

            half_dist = total_dist / 2
            for i in range(1, len(distances)):
                if distances[i] >= half_dist:
                    x1, y1 = points[i-1]
                    x2, y2 = points[i]
                    ratio = (half_dist - distances[i-1]) / (distances[i] - distances[i-1])
                    label_x = int(x1 + ratio * (x2 - x1))
                    label_y = int(y1 + ratio * (y2 - y1))
                    break
            else:
                label_x, label_y = points[len(points)//2]  # fallback

            label_surface = font.render(text, True, color)
            label_surface.set_alpha(ROUTE_LABEL_ALPHA)
            text_rect = label_surface.get_rect(center=(label_x, label_y))

            if DRAW_ROUTE_LABEL_BOX:
                padded_rect = text_rect.inflate(ROUTE_LABEL_BOX_PADDING * 2, ROUTE_LABEL_BOX_PADDING * 2)
                
                pygame.draw.rect(screen, ROUTE_LABEL_BG_COLOR, padded_rect)
                pygame.draw.rect(screen, color, padded_rect, ROUTE_LABEL_BOX_WIDTH)

            screen.blit(label_surface, text_rect)


        except Exception as e:
            print(f"Failed to draw label {label.get('routeNumber', '?')}: {e}")

def color_status(code):
    if code == 200:
        return Fore.GREEN + str(code) + Style.RESET_ALL
    elif code == 404:
        return Fore.RED + str(code) + Style.RESET_ALL
    else:
        return Fore.YELLOW + str(code) + Style.RESET_ALL

def parse_service_page(r):
    try:
        soup = BeautifulSoup(r.text, "html.parser")

        service_id_match = re.search(r"SERVICE_ID\s*=\s*(\d+);", r.text)
        extent_match = re.search(r"EXTENT\s*=\s*(\[[^\]]+\]);", r.text)

        service_id = service_id_match.group(1) if service_id_match else ""
        extent = extent_match.group(1) if extent_match else "" # this data is in the route page in a script at the end, its pretty accurate too, very convenient!

        header = soup.find("h1", class_="service-header")
        route_elem = header.find("strong") if header else None
        route_number = route_elem.text.strip() if route_elem else ""

        frequency = 0
        groupings = soup.find_all("div", class_="grouping")
        for grouping in groupings:
            table = grouping.find("table", class_="timetable")
            if table:
                first_row = table.find("tr")
                if first_row:
                    # count only <td> elements (time cells, not stop names)
                    frequency += len(first_row.find_all("td"))

        page_text = soup.get_text().lower()
        is_public = not any(keyword.lower() in page_text for keyword in PRIVATE_KEYWORDS)

        return {
            "serviceID": service_id,
            "extent": extent,
            "routeNumber": route_number,
            "frequency": frequency,
            "isPublicService": is_public
        }

    except Exception as e:
        print(f"\nFailed to parse page: {e}")
        return None, 0

def download_routes(): # uses both bustimes.org API data and scraped data, because neither has all the data needed
    print(f"{Fore.GREEN}Downloading Routes")

    status_history = [] # for the fancy status code display

    # fetch URLs from the sitemap
    response = requests.get(SERVICES_SITEMAP_URL, headers=HEADERS)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "xml")
    service_urls = [loc.text for loc in soup.find_all("loc")]
    print(f"{Fore.GREEN}Found {len(service_urls)} route URLs")

    # fetch the big json file
    print(f"{Fore.GREEN}Downloading services.json from bustimes.org")
    json_data = requests.get(SERVICES_JSON_URL, headers=HEADERS).json()["results"]
    json_lookup = {
        str(entry["id"]): {
            "mode": entry.get("mode", ""),
            "operator": entry.get("operator", [])
        }
        for entry in json_data
    }

    all_data = []

    print(f"{Fore.GREEN}Scraping route data from bustimes.org:")

    scrape_counter = 0

    try:
        for i, url in enumerate(service_urls, 1):
            route_slug = url.rsplit('/', 1)[-1]

            r = requests.get(url, headers=HEADERS)
            code = r.status_code
            status_history.append(code)
            if len(status_history) > 10:
                status_history.pop(0)

            data = parse_service_page(r)
            if data:
                service_id = str(data["serviceID"])
                if service_id in json_lookup:
                    data["mode"] = json_lookup[service_id]["mode"]
                    data["operator"] = ",".join(json_lookup[service_id]["operator"])
                else:
                    data["mode"] = ""
                    data["operator"] = ""
                all_data.append(data)

            colored_statuses = " ".join(color_status(c) for c in status_history)
            sys.stdout.write(f"\r\033[K{Fore.CYAN}Status: {colored_statuses} {Fore.CYAN}| {Fore.YELLOW}{i}{Fore.CYAN}/{Fore.GREEN}{len(service_urls)} {Fore.CYAN}| Requesting route: {Fore.YELLOW}{route_slug:<25}")
            sys.stdout.flush()

            scrape_counter += 1
            # time.sleep(0.5) # be polite to the server
    except Exception as e:
        print(f"\n{Fore.RED}Error scraping {route_slug:<25} - {e}")
    
    print(f"\n{Fore.GREEN}Successfully scraped {scrape_counter} routes from bustimes.org")

    # sort by frequency
    all_data.sort(key=lambda x: x["frequency"])

    # write csv
    fieldnames = ["serviceID", "extent", "routeNumber", "frequency", "isPublicService", "mode", "operator"]

    with open(ROUTES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_data)

    print(f"{Fore.GREEN}Saved routes to {ROUTES_CSV}")

def download_colors():
    try:
        r = requests.get(OPERATOR_COLORS_URL, headers=HEADERS)

        with open(OPERATOR_COLORS_CSV, "wb") as f:
            f.write(r.content)
        print(f"{Fore.GREEN}Successfully downloaded {OPERATOR_COLORS_CSV}")

    except Exception as e:
        print(f"{Fore.RED}Failed to download {OPERATOR_COLORS_CSV}: {e}")
        sys.exit()

def download_cities():
    try:
        r = requests.get(CITIES_URL, headers=HEADERS)

        with open(CITIES_CSV, "wb") as f:
            f.write(r.content)
        print(f"{Fore.GREEN}Successfully downloaded {CITIES_CSV}")
        
    except Exception as e:
        print(f"{Fore.RED}Failed to download {OPERATOR_COLORS_CSV}: {e}")
        sys.exit()

def download_geometry(start): # scrapes bustimes.org because its much easier to work with than the data in the bustimes.org trips API 
    # work out what the highest route ID is, this should be run after updaing routes.csv
    with open(ROUTES_CSV, newline="") as f:
        reader = csv.DictReader(f)
        end = max(int(row["serviceID"]) for row in reader) + 10

    if start >= end:
        print(f"{Fore.GREEN}Geometry already up to date.")
        return

    print(f"{Fore.GREEN}Downloading geometry for routes {Fore.CYAN}{start}{Fore.GREEN}-{Fore.CYAN}{end}")

    status_history = [] # for the fancy status code display

    for route_id in range(start, end):
        url = GEOMETRY_BASE_URL.format(route_id)
        try:
            r = requests.get(url, headers=HEADERS, timeout=5)
            code = r.status_code
            status_history.append(code)
            if len(status_history) > 10:
                status_history.pop(0)

            if code == 200 and r.headers.get("Content-Type", "").startswith("application/json"):
                with open(os.path.join(GEOMETRY_DIR, f"{route_id}.json"), "w", encoding="utf-8") as f:
                    f.write(r.text)

        except requests.RequestException:
            code = "ERR"
            status_history.append(code)
            if len(status_history) > 10:
                status_history.pop(0)

        # fancy status display
        colored_statuses = " ".join(color_status(c) for c in status_history)
        sys.stdout.write(f"\r{Fore.CYAN}Status: {colored_statuses} {Fore.CYAN}| Requesting geometry: {Fore.YELLOW}{route_id:<7}          ")
        sys.stdout.flush()

    print(f"\n{Fore.GREEN}Finished downloading geometry.")

def check_data():
    if not os.path.exists(MAPS_DIR):
        os.makedirs(MAPS_DIR)
        print(f"{Fore.GREEN}Created maps folder {Fore.YELLOW}{MAPS_DIR}")

    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR) 
        print(f"{Fore.GREEN}Created data folder {Fore.YELLOW}{DATA_DIR}")

    if not os.path.isfile(ROUTES_CSV):
        input(f"{Fore.RED}{ROUTES_CSV} not found {Fore.WHITE}- {Fore.CYAN}Press {Fore.GREEN}[ENTER] {Fore.CYAN}to download from bustimes.org (Takes a while)")
        download_routes()
    elif UPDATE_ROUTES:
        download_routes()

    if not os.path.isfile(OPERATOR_COLORS_CSV):
        input(f"{Fore.RED}{OPERATOR_COLORS_CSV} not found {Fore.WHITE}- {Fore.CYAN}Press {Fore.GREEN}[ENTER] {Fore.CYAN}to download from verumignis.com")
        download_colors()
    elif UPDATE_DATA:
        download_colors()

    if not os.path.isfile(CITIES_CSV):
        input(f"{Fore.RED}{CITIES_CSV} not found {Fore.WHITE}- {Fore.CYAN}Press {Fore.GREEN}[ENTER] {Fore.CYAN}to download from verumignis.com")
        download_cities()
    elif UPDATE_DATA:
        download_cities()

    if not os.path.exists(GEOMETRY_DIR):
        os.makedirs(GEOMETRY_DIR) 
        print(f"{Fore.GREEN}Created geometry folder {Fore.YELLOW}{GEOMETRY_DIR}")
        input(f"{Fore.RED}Geometry data not found {Fore.WHITE}- {Fore.CYAN}Press {Fore.GREEN}[ENTER] {Fore.CYAN}to download from bustimes.org (Takes a while - Requires ~1.5GB)")
        download_geometry(0)
    else:
        numbers = []
        for filename in os.listdir(GEOMETRY_DIR):
            if filename.lower().endswith(".json"):
                name_part = os.path.splitext(filename)[0]
                if name_part.isdigit():
                    numbers.append(int(name_part))

        if numbers:
            next_geometry = max(numbers) + 1
            if UPDATE_GEOMETRY:
                download_geometry(next_geometry)
        else:
            input(f"{Fore.RED}Geometry data not found {Fore.WHITE}- {Fore.CYAN}Press {Fore.GREEN}[ENTER] {Fore.CYAN}to download from bustimes.org (Takes a while - Requires ~1.5GB)")
            download_geometry(0)


def main():
    init(autoreset=True) # for colorama

    ascii_art = f'''{Fore.RED}
     .---------------------------.            .---------------------------.
   .' .--..---..---..---..---..--⹁\\          /,--..---..---..---..---..--. `.
   |_/___||___||___||___||___||___\\\\        //___||___||___||___||___||___\\_|
   |_] ######################## __|]        [|__ ######################## [_|
   |============================/              \\============================|
   ||"""| |"""||"""||"""||"""|  |==.        .==|  |"""||"""||"""||"""| |"""||
   ||=  |="---""---""---""---"======\\      /======"---""---""---""---"=|  =||
   ||== |  ____          *[]    ____|      |____    []*          ____  | ==||
   ||===| //  \\\\               //  \\\\      //  \\\\               //  \\\\ |===||
   `+---+-"\__/"---------------"\__/"      "\__/"---------------"\__/"-+---+'
{Fore.YELLOW}================================================================================{Fore.RED}
 _    ____________  __  ____  ______________   ____________  {Fore.CYAN}  ____  __  _______{Fore.RED}
| |  / / ____/ __ \/ / / /  |/  /  _/ ____/ | / /  _/ ___/ / {Fore.CYAN} / __ )/ / / / ___/{Fore.RED}
| | / / __/ / /_/ / / / / /|_/ // // / __/  |/ // / \__ \|/ {Fore.CYAN} / __  / / / /\__ \ {Fore.RED}
| |/ / /___/ _, _/ /_/ / /  / // // /_/ / /|  // / ___/ /  {Fore.CYAN} / /_/ / /_/ /___/ / {Fore.RED}
|___/_____/_/_|_|\____/_/  /_/___/\____/_/ |_/___//____/ {Fore.CYAN}__/_____/\____//____/
   /  |/  /   |  / __ \   / ____/ ____/ | / / ____/ __ \/   |/_  __/ __ \/ __ \ 
  / /|_/ / /| | / /_/ /  / / __/ __/ /  |/ / __/ / /_/ / /| | / / / / / / /_/ / 
 / /  / / ___ |/ ____/  / /_/ / /___/ /|  / /___/ _, _/ ___ |/ / / /_/ / _, _/  
/_/  /_/_/  |_/_/       \____/_____/_/ |_/_____/_/ |_/_/  |_/_/  \____/_/ |_|   

'''
    print(ascii_art)

    check_data() # make sure all data exists, if not, download it

    min_lon, min_lat, max_lon, max_lat = BOUNDING_BOX
    center_lat = (min_lat + max_lat) / 2
    m_per_deg_lat, m_per_deg_lon = meters_per_degree(center_lat)

    operator_colors = load_operator_colors(OPERATOR_COLORS_CSV)

    width_m = (max_lon - min_lon) * m_per_deg_lon
    height_m = (max_lat - min_lat) * m_per_deg_lat
    width_px = int(width_m / scale_m_per_px)
    height_px = int(height_m / scale_m_per_px)

    pygame.init()
    screen = pygame.display.set_mode((width_px, height_px))
    pygame.display.set_caption(WINDOW_TITLE)
    screen.fill(BACKGROUND_COLOR)

    route_labels = []
    filter_counters = defaultdict(int)
    drawn_count = 0
    last_filter = "None filtered yet"
    counter = 0

    # work out what the file name should be
    numbers = []
    for filename in os.listdir(MAPS_DIR):
        if filename.lower().endswith(".png"):
            name_part = os.path.splitext(filename)[0]
            if name_part.isdigit():
                numbers.append(int(name_part))

    if numbers:
        output_file = str(max(numbers) + 1) + ".png"
    else:
        output_file = "1.png"

    print(f"{Fore.GREEN}Drawing bus map - Output will be saved to {Fore.YELLOW}{os.path.join(MAPS_DIR, output_file)}")

    with open(ROUTES_CSV, newline='', encoding="utf-8") as csvfile:
        total_routes = sum(1 for _ in open(ROUTES_CSV, encoding="utf-8")) - 1 # count the total routes
        csvfile.seek(0) # rewind
        reader = csv.DictReader(csvfile)

        for row in reader:

            counter += 1

            is_public = row.get("isPublicService", "").lower() == "true"
            operator = row.get("operator", "").strip()
            mode = row.get("mode", "").strip()

            # public/private filtering
            if SHOW_ONLY_PRIVATE_ROUTES and is_public:
                filter_counters["Route is public"] += 1
                last_filter = "Route is public"
                print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Route is public          ", end="\r")
                continue
            elif IGNORE_PRIVATE_ROUTES and not is_public:
                filter_counters["Route is private"] += 1
                last_filter = "Route is private"
                print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Route is private          ", end="\r")
                continue

            # mode/operator filtering
            if INCLUDE_OPERATORS and operator not in INCLUDE_OPERATORS:
                filter_counters["Operator not included"] += 1
                last_filter = "Operator not included"
                print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Operator not included          ", end="\r")
                continue
            if operator in EXCLUDE_OPERATORS:
                filter_counters["Operator excluded"] += 1
                last_filter = "Operator excluded"
                print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Operator excluded          ", end="\r")
                continue

            if INCLUDE_MODES and mode not in INCLUDE_MODES:
                filter_counters["Mode not included"] += 1
                last_filter = "Mode not included"
                print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Mode not included          ", end="\r")
                continue
            if mode in EXCLUDE_MODES:
                filter_counters["Mode excluded"] += 1
                last_filter = "Mode excluded"
                print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Mode excluded          ", end="\r")
                continue

            try:
                extent = json.loads(row["extent"])
                route_bbox = tuple(extent)
                if not bbox_intersects(route_bbox, BOUNDING_BOX):
                    filter_counters["Out of bounding box"] += 1
                    last_filter = "Out of bounding box"
                    print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Out of bounding box          ", end="\r")
                    continue

                diagonal = bbox_diagonal_distance(route_bbox, m_per_deg_lat, m_per_deg_lon)
                if diagonal > MAX_ROUTE_LENGTH:
                    filter_counters["Route too long"] += 1
                    last_filter = "Route too long"
                    print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Route too long          ", end="\r")
                    continue

                if diagonal < MIN_ROUTE_LENGTH:
                    filter_counters["Route too short"] += 1
                    last_filter = "Route too short"
                    print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Route too short          ", end="\r")
                    continue

            except Exception as e:
                filter_counters["Bad bounding box"] += 1
                last_filter = "Bad bounding box"
                print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Bad bounding box          ", end="\r")
                continue

            try:
                service_id = row["serviceID"]
                frequency = int(row["frequency"])

                width, brightness = get_style_for_frequency(frequency)
                base_color = get_operator_color(operator, operator_colors)
                color = scale_color(base_color, brightness)

                if width <= 0:
                    filter_counters["Low frequency"] += 1
                    last_filter = "Low frequency"
                    print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Low frequency          ", end="\r")
                    continue

                path = os.path.join(GEOMETRY_DIR, f"{service_id}.json")
                if not os.path.isfile(path):
                    filter_counters["Geometry missing"] += 1
                    last_filter = "Geometry missing"
                    print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Geometry missing          ", end="\r")
                    continue

                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                geometry = data.get("geometry", {})
                geom_type = geometry.get("type")
                coords = geometry.get("coordinates")

                if geom_type == "LineString":
                    coords = [coords]  # wrap in list to reuse same logic as MultiLineString
                elif geom_type == "MultiLineString":
                    pass  # coords already in correct format
                else:
                    filter_counters["Invalid line data"] += 1
                    last_filter = "Invalid line data"
                    print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Invalid line data          ", end="\r")
                    continue

                if segment_too_long(coords, m_per_deg_lat, m_per_deg_lon):
                    filter_counters["Segment too long"] += 1
                    last_filter = "Segment too long"
                    print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}Segment too long          ", end="\r")
                    continue
                
                drawn_count += 1
                print(f"{Fore.CYAN}Drawing {Fore.YELLOW}{counter}{Fore.CYAN}/{Fore.GREEN}{total_routes} {Fore.CYAN}| Last filter: {Fore.YELLOW}{last_filter}          ", end="\r")

                for line in coords:
                    if len(line) < 2:
                        continue
                    points = [
                        geo_to_pixel(lon, lat, min_lon, max_lat, m_per_deg_lat, m_per_deg_lon)
                        for lon, lat in line
                    ]
                    pygame.draw.lines(screen, color, False, points, width)

                if DRAW_ROUTE_LABELS:
                    route_labels.append({
                        "routeNumber": row["routeNumber"],
                        "color": color,
                        "points": points
                    })

                pygame.display.flip()

            except Exception as e:
                print(f"Error processing service {row.get('serviceID', '?')}: {e}") # should never happen
                continue

    draw_route_labels(screen, route_labels, m_per_deg_lat, m_per_deg_lon)
    draw_city_labels(screen, min_lon, max_lat, m_per_deg_lat, m_per_deg_lon)

    pygame.display.flip()
    pygame.image.save(screen, os.path.join(MAPS_DIR, output_file))
    pygame.quit()

    print(f"\n{Fore.GREEN}Finished drawing bus map.\n")
    print(f"{Fore.CYAN}Total routes: {Fore.YELLOW}{counter}")
    print(f"{Fore.CYAN}Drawn routes: {Fore.YELLOW}{drawn_count}\n")
    print(f"{Fore.CYAN}Filtered routes:")
    print(Fore.CYAN + "="*36)

    for reason, count in sorted(filter_counters.items()):
        print(f"{Fore.CYAN}| {Fore.YELLOW}{reason:<25}{Fore.CYAN}| {Fore.YELLOW}{count:<5} {Fore.CYAN}|")

    print(Fore.CYAN + "="*36)

if __name__ == "__main__":
    main()