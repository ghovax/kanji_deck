import json
import urllib.request
import csv
import sys
import requests
from bs4 import BeautifulSoup
import re
import csv
from tqdm import tqdm
import json
import concurrent.futures


def fetch_html_content(kanji):
    """Fetches the HTML content of the kanji page from kakimashou.com."""
    url = f"https://www.kakimashou.com/dictionary/character/{kanji}"
    try:
        response = requests.get(url)
        response.encoding = "utf-8"
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for {kanji}: {e}")
        return None


def extract_readings(readings_div):
    """Extracts kunyomi, onyomi, and nanori readings from the readings div."""
    kunyomi = extract_reading_type(readings_div, "Kun'yomi")
    onyomi = extract_reading_type(readings_div, "On'yomi")
    nanori = extract_reading_type(readings_div, "Nanori")
    return kunyomi, onyomi, nanori


def extract_reading_type(readings_div, reading_type):
    """Extracts a specific type of reading (kunyomi, onyomi, or nanori)."""
    readings = {}
    header = readings_div.find("h5", string=reading_type)
    if header:
        reading_list = header.find_next_sibling("ul")
        if reading_list:
            for item in reading_list.find_all("li"):
                reading_table = item.find("table", lang="ja")
                meaning_span = item.find("span", class_="readingMeaning")
                if reading_table:
                    reading = "".join(
                        cell.text for cell in reading_table.find_all("td") if cell.text
                    ).strip("-")
                    meaning = meaning_span.get_text(strip=True) if meaning_span else ""
                    readings[reading] = readings.get(reading, "") + (
                        ", " + meaning if readings.get(reading) else meaning
                    )
    return readings


def extract_kanji_usage_data(soup):
    """Extracts kanji usage data from the tables on the page."""
    kanji_data = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                link = cells[0].find("a")
                if link:
                    reading_spans = link.find_all("span", class_="reading")
                    readings = [
                        "".join(
                            child.string
                            for child in span.children
                            if child.string and child.name != "em"
                        )
                        for span in reading_spans
                    ]
                    if readings:
                        reading = readings[0]
                        percentage = float(cells[1].text.replace("%", ""))
                        if percentage != 0.0:
                            hiragana_reading = "".join(re.findall(r"[ぁ-ん]", reading))
                            katakana_reading = "".join(re.findall(r"[ァ-ン]", reading))
                            if hiragana_reading:
                                kanji_data.append(
                                    {
                                        "reading": hiragana_reading,
                                        "type": "hiragana",
                                        "percentage": percentage,
                                    }
                                )
                            if katakana_reading:
                                kanji_data.append(
                                    {
                                        "reading": katakana_reading,
                                        "type": "katakana",
                                        "percentage": percentage,
                                    }
                                )
    kanji_data.sort(key=lambda x: x["percentage"], reverse=True)
    return kanji_data


def filter_and_sort_readings(kunyomi, onyomi, nanori, kanji_usage_data):
    """Filters out 0% commonality readings and sorts by percentage."""
    reading_percentages = {
        item["reading"]: item["percentage"] for item in kanji_usage_data
    }

    return (
        filter_and_sort_reading_type(kunyomi, reading_percentages),
        filter_and_sort_reading_type(onyomi, reading_percentages),
        filter_and_sort_reading_type(nanori, reading_percentages),
    )


def filter_and_sort_reading_type(reading_type_dict, reading_percentages):
    """Filters and sorts a specific reading type dictionary."""
    return {
        reading: {"meaning": meaning, "percentage": reading_percentages[reading]}
        for reading, meaning in sorted(
            reading_type_dict.items(),
            key=lambda item: reading_percentages.get(item[0], 0),
            reverse=True,
        )
        if reading in reading_percentages
    }


def fetch_kanji_data(kanji):
    """Fetches and processes kanji data for a given kanji."""
    soup = fetch_html_content(kanji)
    if not soup:
        return None

    readings_div = soup.select_one(
        "#bodyTag > div > div > div > div:nth-child(1) > div.col-xl-8.col-lg-7.col-md-6 > div > div.col-lg-9.col-md-9.col-sm-10 > div"
    )
    if not readings_div:
        print(f"Readings div not found for {kanji}")
        return None

    kunyomi, onyomi, nanori = extract_readings(readings_div)
    kanji_usage_data = extract_kanji_usage_data(soup)
    filtered_kunyomi, filtered_onyomi, filtered_nanori = filter_and_sort_readings(
        kunyomi, onyomi, nanori, kanji_usage_data
    )

    return {
        "kanji": kanji,
        "kunyomi": filtered_kunyomi,
        "onyomi": filtered_onyomi,
        "nanori": filtered_nanori,
    }


def load_kanji_list(filepath):
    """Loads the list of kanji from a file."""
    try:
        with open(filepath, "r") as file:
            return [row[0] for row in csv.reader(file, delimiter="\t")]
    except FileNotFoundError:
        print(f"Error: File not found at {filepath}")
        return None


def request(action, **params):
    return {"action": action, "params": params, "version": 6}


def invoke(action, **params):
    requestJson = json.dumps(request(action, **params)).encode("utf-8")
    response = json.load(
        urllib.request.urlopen(
            urllib.request.Request("http://localhost:8765", requestJson)
        )
    )
    if len(response) != 2:
        raise Exception("response has an unexpected number of fields")
    if "error" not in response:
        raise Exception("response is missing required error field")
    if "result" not in response:
        raise Exception("response is missing required result field")
    if response["error"] is not None:
        raise Exception(response["error"])
    return response["result"]


def main():
    """Main function to fetch and save kanji data."""
    kanjis = load_kanji_list("All JLPT Kanjis.txt")
    if not kanjis:
        return

    with concurrent.futures.ThreadPoolExecutor() as executor:
        kanji_data = list(
            tqdm(
                executor.map(fetch_kanji_data, kanjis),
                total=len(kanjis),
                desc="Fetching kanji data from kakimashou.com",
                dynamic_ncols=True,
                unit="kanji",
                bar_format="Fetching kanji data: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]",
            )
        )

    kanji_data = [data for data in kanji_data if data]

    with open("kanji_data.json", "w") as file:
        json.dump(kanji_data, file, indent=4, ensure_ascii=False)

    print("Kanji data saved to kanji_data.json")

    # Load the dictionary from the JSON file
    with open("kanji_data.json", "r", encoding="utf-8") as f:
        kanji_data = json.load(f)

    reference_kanjis = []
    # Parse the CSV file and get the second column
    with open("All JLPT Kanjis.txt", "r") as file:
        reader = csv.reader(file, delimiter="\t")
        for row in reader:
            reference_kanjis.append(row[0])

    # Iterate through each kanji in reference_kanjis with tqdm progress bar
    for target_kanji in tqdm(
        reference_kanjis,
        desc="Updating the Anki deck",
        unit="kanji",
    ):
        kanji_entry = None
        for entry in kanji_data:
            if entry["kanji"] == target_kanji:
                kanji_entry = entry
                break

        if kanji_entry is None:
            print(f"Kanji '{target_kanji}' not found in the JSON data")
        else:
            # Prepare the readings with <br> tags for line breaks
            katakana_readings = []
            hiragana_readings = []
            names_readings = []

            if "onyomi" in kanji_entry:
                for reading, details in kanji_entry["onyomi"].items():
                    meaning = details["meaning"]
                    percentage = details["percentage"]
                    if percentage < 1:
                        katakana_readings.append(
                            f"<span style='color: gray;'>{reading}</span> <span style='font-size: 60%;'>{meaning}</span>"
                        )
                    else:
                        katakana_readings.append(
                            f"{reading} <span style='font-size: 60%;'>{meaning}</span>"
                        )

            if "kunyomi" in kanji_entry:
                for reading, details in kanji_entry["kunyomi"].items():
                    meaning = details["meaning"]
                    percentage = details["percentage"]
                    if percentage < 1:
                        hiragana_readings.append(
                            f"<span style='color: gray;'>{reading}</span> <span style='font-size: 60%;'>{meaning}</span>"
                        )
                    else:
                        hiragana_readings.append(
                            f"{reading} <span style='font-size: 60%;'>{meaning}</span>"
                        )

            if "nanori" in kanji_entry:
                for reading, details in kanji_entry["nanori"].items():
                    meaning = details["meaning"]
                    percentage = details["percentage"]
                    if percentage < 1:
                        names_readings.append(
                            f"<span style='color: gray;'>{reading}</span> <span style='font-size: 60%;'>{meaning}</span>"
                        )
                    else:
                        names_readings.append(
                            f"{reading} <span style='font-size: 60%;'>{meaning}</span>"
                        )

            katakana_reading = "<br>".join(katakana_readings)
            hiragana_reading = "<br>".join(hiragana_readings)
            names_reading = "<br>".join(names_readings)

            # Find the note IDs for the target kanji in Anki
            note_ids = invoke(
                "findNotes", query=f'"deck:All JLPT Kanjis" Kanji:{target_kanji}'
            )

            if not note_ids:
                print(
                    f"No notes found for '{target_kanji}' in the 'All JLPT Kanjis' deck"
                )
            else:
                # Update each note
                for note_id in note_ids:
                    invoke(
                        "updateNoteFields",
                        note={
                            "id": note_id,
                            "fields": {
                                "KatakanaReading": katakana_reading,
                                "HiraganaReading": hiragana_reading,
                                "NamesReadings": names_reading,
                            },
                        },
                    )


if __name__ == "__main__":
    main()
