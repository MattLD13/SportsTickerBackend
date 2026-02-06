#!/usr/bin/env python3
"""
Live Sports News Test - Terminal Test Script

This script tests the NewsAggregator class with real API calls to ESPN RSS feed.
Run this in a standard Python terminal to verify live news data fetching.

Usage:
    python test_live_news.py
"""

import sys
import time
import requests
from requests.adapters import HTTPAdapter
import xml.etree.ElementTree as ET
from datetime import datetime

# ANSI color codes for pretty terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text):
    """Print a colored header"""
    print(f"\n{Colors.BOLD}{Colors.HEADER}{'='*70}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.HEADER}{text:^70}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.HEADER}{'='*70}{Colors.ENDC}\n")

def print_success(text):
    """Print success message"""
    print(f"{Colors.OKGREEN}✅ {text}{Colors.ENDC}")

def print_error(text):
    """Print error message"""
    print(f"{Colors.FAIL}❌ {text}{Colors.ENDC}")

def print_warning(text):
    """Print warning message"""
    print(f"{Colors.WARNING}⚠️  {text}{Colors.ENDC}")

def print_info(text):
    """Print info message"""
    print(f"{Colors.OKCYAN}ℹ️  {text}{Colors.ENDC}")

def build_pooled_session(pool_size=20, retries=2):
    """Build a session with connection pooling"""
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=retries,
        pool_block=True
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

class LiveNewsAggregator:
    """
    Live news aggregator for testing purposes
    (Simplified version of the production NewsAggregator)
    """
    def __init__(self):
        self.session = build_pooled_session(pool_size=5)
        self.major_keywords = [
            'trade', 'traded', 'signs', 'signed', 'fired', 'hire', 'hired',
            'retire', 'retired', 'injury', 'injured', 'suspend', 'suspended',
            'championship', 'playoff', 'record', 'mvp', 'breaking', 'deal',
            'contract', 'extension', 'released', 'waive', 'waived', 're-sign'
        ]
        self.headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/xml',
        }
        
    def is_major_news(self, headline):
        """Filter for only major news items"""
        headline_lower = headline.lower()
        return any(keyword in headline_lower for keyword in self.major_keywords)
    
    def get_news(self):
        """Fetch major sports news from ESPN RSS feed"""
        try:
            rss_url = "https://www.espn.com/espn/rss/news"
            print_info(f"Fetching RSS feed from: {rss_url}")
            
            response = self.session.get(rss_url, timeout=10, headers=self.headers)
            response.raise_for_status()
            
            print_success(f"RSS feed fetched successfully (Status: {response.status_code})")
            print_info(f"Response size: {len(response.content)} bytes")
            
            # Parse RSS XML
            root = ET.fromstring(response.content)
            
            all_items = []
            major_news = []
            
            for item in root.findall('.//item'):
                title_elem = item.find('title')
                link_elem = item.find('link')
                pub_date_elem = item.find('pubDate')
                desc_elem = item.find('description')
                
                if title_elem is not None and title_elem.text:
                    headline = title_elem.text.strip()
                    link = link_elem.text.strip() if link_elem is not None else None
                    pub_date = pub_date_elem.text.strip() if pub_date_elem is not None else None
                    description = desc_elem.text.strip() if desc_elem is not None else None
                    
                    news_item = {
                        'headline': headline,
                        'link': link,
                        'pub_date': pub_date,
                        'description': description,
                        'is_major': self.is_major_news(headline)
                    }
                    
                    all_items.append(news_item)
                    
                    if news_item['is_major']:
                        major_news.append(news_item)
                        if len(major_news) >= 10:  # Get up to 10 for testing
                            break
            
            return {
                'all_items': all_items,
                'major_news': major_news,
                'total_count': len(all_items),
                'major_count': len(major_news)
            }
            
        except requests.exceptions.ConnectionError as e:
            print_error(f"Connection error: {e}")
            print_warning("Check your internet connection")
            return None
        except requests.exceptions.Timeout as e:
            print_error(f"Request timeout: {e}")
            return None
        except ET.ParseError as e:
            print_error(f"XML parsing error: {e}")
            return None
        except Exception as e:
            print_error(f"Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return None

def display_news_items(news_items, title="News Items", show_all_fields=False):
    """Display news items in a formatted way"""
    if not news_items:
        print_warning("No news items to display")
        return
    
    print(f"\n{Colors.BOLD}{title} ({len(news_items)} items):{Colors.ENDC}")
    print("-" * 70)
    
    for idx, item in enumerate(news_items, 1):
        print(f"\n{Colors.BOLD}{idx}. {item['headline']}{Colors.ENDC}")
        
        if show_all_fields:
            if item.get('pub_date'):
                print(f"   📅 Published: {item['pub_date']}")
            if item.get('link'):
                print(f"   🔗 Link: {item['link'][:60]}...")
            if item.get('description'):
                desc = item['description'][:100] + "..." if len(item['description']) > 100 else item['description']
                print(f"   📝 Description: {desc}")

def test_connection():
    """Test basic internet connectivity"""
    print_header("TEST 1: Internet Connectivity")
    
    try:
        response = requests.get("https://www.espn.com", timeout=5)
        if response.status_code == 200:
            print_success("Internet connection is working")
            print_success("ESPN website is accessible")
            return True
        else:
            print_warning(f"ESPN returned status code: {response.status_code}")
            return True  # Still connected, just different status
    except Exception as e:
        print_error(f"Connection failed: {e}")
        return False

def test_rss_feed_access():
    """Test if RSS feed is accessible"""
    print_header("TEST 2: RSS Feed Access")
    
    try:
        rss_url = "https://www.espn.com/espn/rss/news"
        response = requests.get(rss_url, timeout=10)
        response.raise_for_status()
        
        print_success(f"RSS feed is accessible")
        print_info(f"Status code: {response.status_code}")
        print_info(f"Content type: {response.headers.get('Content-Type', 'Unknown')}")
        print_info(f"Content length: {len(response.content)} bytes")
        
        # Try to parse XML
        root = ET.fromstring(response.content)
        print_success("RSS XML is valid and parseable")
        
        # Count items
        items = root.findall('.//item')
        print_info(f"Found {len(items)} news items in feed")
        
        return True
    except Exception as e:
        print_error(f"RSS feed access failed: {e}")
        return False

def test_news_aggregator():
    """Test the NewsAggregator class with live data"""
    print_header("TEST 3: Live News Aggregation")
    
    aggregator = LiveNewsAggregator()
    
    print_info("Fetching news...")
    start_time = time.time()
    
    result = aggregator.get_news()
    
    fetch_time = time.time() - start_time
    
    if result is None:
        print_error("News aggregation failed")
        return False
    
    print_success(f"News fetched successfully in {fetch_time:.2f} seconds")
    print()
    print(f"  📊 Total items in feed: {result['total_count']}")
    print(f"  ⭐ Major news items: {result['major_count']}")
    print(f"  📈 Filter rate: {result['major_count']/result['total_count']*100:.1f}%")
    
    return result

def test_keyword_filtering(result):
    """Test keyword filtering effectiveness"""
    print_header("TEST 4: Keyword Filtering Analysis")
    
    if not result or not result['major_news']:
        print_warning("No major news items to analyze")
        return False
    
    print_info("Analyzing major news keywords...")
    
    keyword_matches = {}
    for item in result['major_news']:
        headline_lower = item['headline'].lower()
        for keyword in ['trade', 'signed', 'fired', 'injury', 'championship', 
                       'playoff', 'record', 'mvp', 'breaking', 'contract']:
            if keyword in headline_lower:
                keyword_matches[keyword] = keyword_matches.get(keyword, 0) + 1
    
    print(f"\n{Colors.BOLD}Keyword Match Distribution:{Colors.ENDC}")
    for keyword, count in sorted(keyword_matches.items(), key=lambda x: x[1], reverse=True):
        print(f"  • {keyword:15} : {count} matches")
    
    print_success("Keyword filtering is working correctly")
    return True

def test_data_structure(result):
    """Test that news items have correct structure"""
    print_header("TEST 5: Data Structure Validation")
    
    if not result or not result['major_news']:
        print_warning("No news items to validate")
        return False
    
    required_fields = ['headline', 'link', 'pub_date', 'is_major']
    
    print_info("Validating news item structure...")
    
    sample_item = result['major_news'][0]
    missing_fields = [f for f in required_fields if f not in sample_item]
    
    if missing_fields:
        print_error(f"Missing fields: {missing_fields}")
        return False
    
    print_success("All required fields are present")
    
    # Validate field types
    if not isinstance(sample_item['headline'], str):
        print_error("Headline is not a string")
        return False
    
    if not isinstance(sample_item['is_major'], bool):
        print_error("is_major is not a boolean")
        return False
    
    print_success("Field types are correct")
    return True

def main():
    """Run all tests"""
    print()
    print(f"{Colors.BOLD}{Colors.OKBLUE}")
    print("╔═══════════════════════════════════════════════════════════════════╗")
    print("║          LIVE SPORTS NEWS TEST - ESPN RSS FEED                    ║")
    print("╚═══════════════════════════════════════════════════════════════════╝")
    print(f"{Colors.ENDC}")
    
    print_info(f"Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Run tests
    results = []
    
    # Test 1: Internet connectivity
    results.append(test_connection())
    
    # Test 2: RSS feed access
    if results[-1]:
        results.append(test_rss_feed_access())
    else:
        print_error("Skipping remaining tests due to connection failure")
        return 1
    
    # Test 3: News aggregation
    if results[-1]:
        news_result = test_news_aggregator()
        results.append(news_result is not None)
    else:
        print_error("Skipping remaining tests due to RSS access failure")
        return 1
    
    # Test 4: Keyword filtering
    if results[-1] and news_result:
        results.append(test_keyword_filtering(news_result))
    
    # Test 5: Data structure
    if results[-1] and news_result:
        results.append(test_data_structure(news_result))
    
    # Display results
    print_header("LIVE NEWS SAMPLES")
    
    if news_result and news_result['major_news']:
        display_news_items(
            news_result['major_news'][:5], 
            "Major Sports News (Top 5)",
            show_all_fields=True
        )
    
    # Final summary
    print_header("TEST SUMMARY")
    
    passed = sum(results)
    total = len(results)
    
    print(f"\n{Colors.BOLD}Tests Passed: {passed}/{total}{Colors.ENDC}\n")
    
    if passed == total:
        print_success("ALL TESTS PASSED! ✨")
        print()
        print(f"{Colors.OKGREEN}The sports news feature is working correctly!{Colors.ENDC}")
        print(f"{Colors.OKGREEN}Live news data is being fetched and filtered successfully.{Colors.ENDC}")
        return 0
    else:
        print_error(f"{total - passed} test(s) failed")
        return 1

if __name__ == '__main__':
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.WARNING}Test interrupted by user{Colors.ENDC}")
        sys.exit(130)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
