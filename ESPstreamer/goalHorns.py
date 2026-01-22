import os
import requests
from bs4 import BeautifulSoup
import yt_dlp
from urllib.parse import urljoin

# Configuration
BASE_URL = "https://www.thefaceoff.net/goalhorns"
OUTPUT_FOLDER = "NHL_Goal_Horns"

def get_soup(url):
    """Fetches the URL and returns a BeautifulSoup object."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def find_team_links(soup):
    """Finds all internal team pages linked from the main page."""
    team_links = set()
    if not soup:
        return team_links

    # Look for links that contain '/goalhorns/' but are not the main page itself
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        full_url = urljoin(BASE_URL, href)
        
        # Filter for relevant sub-pages (basic heuristic)
        if "/goalhorns/" in full_url and full_url != BASE_URL:
            team_links.add(full_url)
            
    return list(team_links)

def extract_youtube_url(page_url):
    """Scrapes a specific team page to find a YouTube embed or link."""
    soup = get_soup(page_url)
    if not soup:
        return None

    # 1. Check for iframes (standard embeds)
    for iframe in soup.find_all('iframe'):
        src = iframe.get('src', '')
        if 'youtube.com' in src or 'youtu.be' in src:
            return src

    # 2. Check for direct links
    for a in soup.find_all('a', href=True):
        href = a['href']
        if 'youtube.com/watch' in href or 'youtu.be/' in href:
            return href

    return None

def download_and_convert(youtube_url, folder):
    """Downloads audio from YouTube URL and converts to MP3 using yt-dlp."""
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': f'{folder}/%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            print(f"Successfully downloaded: {info.get('title', 'Unknown Title')}")
    except Exception as e:
        print(f"Failed to download {youtube_url}: {e}")

def main():
    # Create output directory
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    print(f"Scanning {BASE_URL} for team pages...")
    soup = get_soup(BASE_URL)
    team_pages = find_team_links(soup)
    
    print(f"Found {len(team_pages)} potential team pages.")

    count = 0
    for page in team_pages:
        # Determine a rough team name from URL for logging
        team_name = page.split('/')[-1].replace('-', ' ').title()
        print(f"Checking page: {team_name}...")
        
        yt_link = extract_youtube_url(page)
        
        if yt_link:
            print(f"  Found YouTube link: {yt_link}")
            print(f"  Downloading and converting...")
            download_and_convert(yt_link, OUTPUT_FOLDER)
            count += 1
        else:
            print(f"  No YouTube link found on {team_name} page.")

    print(f"\nDone! Downloaded {count} goal horns to '{OUTPUT_FOLDER}/'.")

if __name__ == "__main__":
    main()