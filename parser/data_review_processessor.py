from __future__ import annotations
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, TypedDict


class Review(TypedDict, total=False):
    review_id: str
    author_name: str
    author_id: Optional[str]
    author_image_logo: Optional[str]
    author_images: Optional[List[str]]
    author_url: Optional[str]
    rating: float
    sub_ratings: Optional[Dict[str, int]]
    review_text: str
    published_at: str
    date: Optional[str]
    review_date: Optional[str]
    createdAt: Optional[str]
    source: str
    language: str
    trip_type: Optional[str]
    review_count: Optional[int]
    details: Optional[Dict[str, Any]]
    property_response: Optional[str]
    property_author: Optional[str]
    response_date: Optional[str]
    urls: Optional[Dict[str, Optional[str]]]



def parse_reviews_from_response(response: str) -> List[Review]:
    """
    Consumes one raw Google Travel batchexecute response and
    returns standardized review objects.
    """
    def unescape_data(content: str) -> str:
        """Properly unescape the data by handling double escaping."""
        content = content.replace('\\\\"', '"')
        content = content.replace('\\\\u003d', '=')
        content = content.replace('\\\\u0026', '&')
        content = content.replace('\\\\n', '\n')
        content = content.replace('\\\\t', '\t')
        content = content.replace('\\\\\\\\', '\\')
        content = content.replace('\\"', '"')
        content = content.replace('\\u003d', '=')
        content = content.replace('\\u0026', '&')
        content = content.replace('\\n', '\n')
        content = content.replace('\\t', '\t')
        content = content.replace('\\\\', '\\')
        return content

    def parse_relative_date(date_str: Optional[str]) -> Optional[datetime]:
        """Parse various relative date formats and return absolute date."""
        if not date_str or date_str in ["Unknown", "null", "None"]:
            return None
        
        date_str = date_str.lower().strip()
        current_date = datetime.now()
        
        day_match = re.search(r'(\d+)?\s*days?\s*ago', date_str)
        if day_match:
            days = int(day_match.group(1)) if day_match.group(1) else 1
            return current_date - timedelta(days=days)
        
        week_match = re.search(r'(\d+)?\s*weeks?\s*ago', date_str)
        if week_match:
            weeks = int(week_match.group(1)) if week_match.group(1) else 1
            return current_date - timedelta(weeks=weeks)
        
        month_match = re.search(r'(\d+)?\s*months?\s*ago', date_str)
        if month_match:
            months = int(month_match.group(1)) if month_match.group(1) else 1
            return current_date - timedelta(days=months * 30)
        
        year_match = re.search(r'(\d+)?\s*years?\s*ago', date_str)
        if year_match:
            years = int(year_match.group(1)) if year_match.group(1) else 1
            return current_date - timedelta(days=years * 365)
        
        hour_match = re.search(r'(\d+)?\s*hours?\s*ago', date_str)
        if hour_match:
            hours = int(hour_match.group(1)) if hour_match.group(1) else 1
            return current_date - timedelta(hours=hours)
        
        minute_match = re.search(r'(\d+)?\s*minutes?\s*ago', date_str)
        if minute_match:
            minutes = int(minute_match.group(1)) if minute_match.group(1) else 1
            return current_date - timedelta(minutes=minutes)
        
        if 'just now' in date_str:
            return current_date
        
        return None

    def format_datetime(dt: Optional[datetime]) -> Optional[str]:
        """Format datetime to ISO format with timezone."""
        if dt:
            return dt.strftime('%Y-%m-%dT00:00:00+07:00')
        return None

    def detect_format(file_content: str) -> str:
        """Detect which format the file is using."""
        if 'MapsUgcPostService.ListUgcPosts' in file_content:
            return 'maps_ugc'
        elif 'ocp93e' in file_content:
            return 'ocp93e'
        elif '["wrb.fr","/MapsUgcPostService.ListUgcPosts"' in file_content:
            return 'maps_ugc'
        elif '["wrb.fr","ocp93e"' in file_content:
            return 'ocp93e'
        else:
            return 'unknown'

    def clean_null_values(obj: Any) -> Any:
        """Recursively replace 'Unknown' and 'null' strings with None."""
        if isinstance(obj, dict):
            result: Dict[str, Any] = {}
            for k, v in obj.items(): # type: ignore
                cleaned_v = clean_null_values(v)
                if cleaned_v is not None:
                    result[k] = cleaned_v
            return result
        elif isinstance(obj, list):
            result_list: List[Any] = []
            for item in obj: # type: ignore
                cleaned_item = clean_null_values(item)
                if cleaned_item is not None:
                    result_list.append(cleaned_item)
            return result_list
        elif isinstance(obj, str):
            if obj in ["Unknown", "null", "None", ""]:
                return None
            return obj
        else:
            return obj

    def extract_original_text(text: str) -> str:
        """Extract the original text from a string that contains both translated and original."""
        if not text:
            return text
        
        patterns = [
            r'\(Original\)\s*<br\s*/?>\s*([^<]+(?:<br\s*/?>\s*[^<]+)*)',
            r'\(Original\)\s*\n\s*([^\n]+(?:\n\s*[^\n]+)*)',
            r'\(Original\)\s*([^(]+?(?:\s*\(|$))',
            r'\(Original\)\s*(.+?)(?=\s*(?:\(|$))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                original_text = match.group(1).strip()
                original_text = re.sub(r'<br\s*/?>', '\n', original_text)
                return original_text.strip()
        
        if text.startswith('(Translated by Google)'):
            parts = re.split(r'\(Original\)', text, flags=re.IGNORECASE)
            if len(parts) > 1:
                original_text = parts[1].strip()
                original_text = re.sub(r'<br\s*/?>', '\n', original_text)
                return original_text.strip()
        
        return text

    def extract_response_original_text(response_parts: List[str]) -> str:
        """Extract the original text from a response array."""
        if not response_parts:
            return ""
        
        has_original: bool = False
        original_parts: List[str] = []
        
        for part in response_parts:
            if has_original:
                original_parts.append(part)
            elif '(Original)' in part:
                has_original = True
                split_parts: List[str] = re.split(r'\(Original\)\s*', part, flags=re.IGNORECASE)
                if len(split_parts) > 1:
                    original_parts.append(split_parts[1].strip())
        
        if original_parts:
            return " ".join(original_parts).strip()
        
        return " ".join(response_parts).strip()

    def extract_property_author_from_response(response_text: str) -> Optional[str]:
        """Extract the property author name from the response text."""
        if not response_text:
            return None

        # Clean the text first - normalize newlines and spaces
        cleaned_text = re.sub(r'\s+', ' ', response_text).strip()

        # ============= PRIMARY: Take last segment after final comma =============
        # e.g. "...Warm regards, Management" -> "Management"
        # e.g. "...Warm regards, John Smith" -> "John Smith"
        primary_match = re.search(r',\s*([^,]+?)\s*[.]?\s*$', cleaned_text)
        if primary_match:
            candidate: str = primary_match.group(1).strip()

            # Validate: short enough and no lowercase sentence words
            forbidden_words = {
                'for', 'the', 'and', 'with', 'from', 'your', 'our', 'this',
                'that', 'have', 'will', 'been', 'thank', 'thanks', 'review',
                'wonderful', 'delighted', 'appreciate', 'kind', 'hear', 'look',
                'forward', 'welcoming', 'back', 'enjoyed', 'comfortable',
                'excellent', 'service', 'location', 'truly', 'feedback', 'very',
                'much', 'all', 'us', 'we', 'you', 'my', 'me', 'please', 'time',
                'taking', 'share', 'sharing', 'hope', 'again', 'soon', 'future',
                'rating', 'loyalty', 'host', 'warm', 'regards', 'management',
                'dear', 'hello', 'hi', 'thanks', 'thankyou',
            }

            candidate_words = candidate.split()
            candidate_lower_words = [w.lower().strip('.,!?;:') for w in candidate_words]

            # Valid if: 1-4 words, none are forbidden, not too long
            is_valid: bool = (
                1 <= len(candidate_words) <= 4
                and len(candidate) < 60
                and not any(w in forbidden_words for w in candidate_lower_words)
            )

            if is_valid:
                return candidate[:120]

        # ============= FALLBACK 1: Known role titles anywhere =============
        role_pattern = r'\b(Management|General Manager|Duty Manager|Guest Service Manager|Guest Services Manager|Front Desk Manager|Operations Manager|Property Manager|Resident Manager|Hotel Manager|Assistant Manager|Manager|Front Desk|Reception|Guest Services|Executive Assistant|Owner|Director|Supervisor|Host|Hostess|Chef|Concierge|Staff|Team)\b'
        role_match = re.search(role_pattern, cleaned_text, re.IGNORECASE)
        if role_match:
            return role_match.group(1).strip()[:120]

        # ============= FALLBACK 2: Name before a sign-off phrase =============
        signoff_pattern = r'(?:Best|Kind|Warm)\s+regards\s*,?\s*\n?\s*([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})'
        signoff_match = re.search(signoff_pattern, cleaned_text)
        if signoff_match:
            candidate = signoff_match.group(1).strip()
            if 1 <= len(candidate.split()) <= 3:
                return candidate[:120]

        # ============= STRICT DEFAULT =============
        return "Management"

    def extract_review_urls(review_block: str) -> Dict[str, Optional[str]]:
        """Extract auxiliary URLs from a review block and return them as a dict.
        
        Note: author_url and author_avatar_url are already top-level fields
        on the review object, so they are not duplicated here.
        """
        
        def find_first(pattern: str) -> Optional[str]:
            match = re.search(pattern, review_block)
            if match:
                url = match.group(0)
                # Unescape common sequences
                url = url.replace('\\u003d', '=').replace('\\u0026', '&')
                url = url.replace('\\\\u003d', '=').replace('\\\\u0026', '&')
                url = url.replace('\\/', '/')
                url = re.sub(r'\\\\', '', url)
                return url
            return None

        return {
            "direct_review_link": find_first(r'https://www\.google\.com/maps/reviews/data=[^\s"\\]+'),
            "report_url": find_first(r'https://www\.google\.com/local/content/rap/report\?[^\s"\\]+'),
            "reply_url": find_first(r'https://business\.google\.com/local/business/\d+/customers/reviews/reply\?[^\s"\\]+'),
            "delete_reply_url": find_first(r'https://business\.google\.com/local/business/\d+/customers/reviews/deletereply\?[^\s"\\]+'),
        }

    def extract_property_response_from_block(review_block: str) -> Optional[Dict[str, Any]]:
        """
        Extract property response from a review block.
        Handles ocp93e, qv9Egd, and nested response formats.
        """
        response: Optional[Dict[str, Any]] = None

        # ============= NEW: Nested response format (qv9Egd / newer) =============
        # Pattern captures response text AND the epoch timestamp in one shot
        nested_response_pattern = r'"((?:Dear|Hello|Hi|Thank|Greetings|Good|To whom)[^"]*(?:\\.[^"]*)*?)"\s*,\s*null\s*,\s*\[\d+\s*,\s*\d+\]\s*\]+\s*\]*\s*,\s*\[null\s*,\s*(\d{13,16})\s*,'
        nested_match = re.search(nested_response_pattern, review_block, re.DOTALL)
        if nested_match:
            response_text = nested_match.group(1)
            response_text = response_text.replace('\\n', '\n').replace('\\"', '"')
            response_text = response_text.strip()

            if response_text and len(response_text) > 10:
                response_date: Optional[str] = None

                # Epoch timestamp (microseconds) is captured as group 2
                epoch_str = nested_match.group(2)
                if epoch_str:
                    try:
                        epoch_us = int(epoch_str)
                        dt = datetime.fromtimestamp(epoch_us / 1_000_000)
                        response_date = dt.strftime('%Y-%m-%dT00:00:00+07:00')
                    except Exception:
                        pass

                # Fallback: look for a relative date near the match
                if not response_date:
                    following_text = review_block[nested_match.end():nested_match.end() + 300]
                    rel_match = re.search(r'"(\d+\s+\w+\s+ago|a\s+\w+\s+ago|just now|\d+\s+hours?\s+ago)"', following_text)
                    if rel_match:
                        response_date = rel_match.group(1)

                property_author = extract_property_author_from_response(response_text) or "Management"
                response = {
                    "property_response": response_text,
                    "property_author": property_author,
                }
                if response_date:
                    response["response_date"] = response_date

                return response

        # ============= Multi-part array (older ocp93e) =============
        # Format: [["Dear...", "Thank you...", "Warm regards,", "Management"], "a day ago"]
        multi_part_pattern = r'\[\[((?:"(?:[^"\\]|\\.)*"(?:\s*,\s*"(?:[^"\\]|\\.)*")+))\]\s*,\s*"([^"]+)"\]'
        multi_match = re.search(multi_part_pattern, review_block)
        if multi_match:
            parts_str: str = multi_match.group(1)
            response_date_rel: str = multi_match.group(2)

            text_parts: List[str] = re.findall(r'"((?:[^"\\]|\\.)*)"', parts_str)
            meaningful_parts: List[str] = [p.strip() for p in text_parts if p.strip()]

            if meaningful_parts:
                response_text = " ".join(meaningful_parts)
                response_text = response_text.replace('\\n', '\n').replace('\\"', '"')

                author_candidate: str = meaningful_parts[-1].strip().rstrip(',').rstrip('.')
                author_words = author_candidate.split()
                forbidden_words = {
                    'for', 'the', 'and', 'with', 'from', 'your', 'our', 'this',
                    'that', 'have', 'will', 'been', 'thank', 'thanks', 'review',
                    'wonderful', 'delighted', 'appreciate', 'kind', 'hear', 'look',
                    'forward', 'welcoming', 'back', 'enjoyed', 'comfortable',
                    'excellent', 'service', 'location', 'truly', 'feedback',
                }
                is_valid_author: bool = (
                    1 <= len(author_words) <= 4
                    and not any(w.lower() in forbidden_words for w in author_words)
                    and author_candidate
                    and len(author_candidate) < 60
                )

                property_author = author_candidate if is_valid_author else (
                    extract_property_author_from_response(response_text) or "Management"
                )

                response = {
                    "property_response": response_text,
                    "response_date": response_date_rel,
                    "property_author": property_author
                }
                return response

        # ============= Original ocp93e format =============
        response_match = re.search(r'\[\s*\[([^\]]*?)\]\s*,\s*"([^"]+)"\s*\]', review_block)
        if response_match:
            response_parts_str: str = response_match.group(1)
            response_date_rel: str = response_match.group(2)

            text_parts: List[str] = re.findall(r'"([^"]*)"', response_parts_str)
            meaningful_parts: List[str] = [p.strip() for p in text_parts if p.strip()]

            if meaningful_parts:
                has_original: bool = any('(Original)' in part for part in meaningful_parts)
                if has_original:
                    response_text = extract_response_original_text(meaningful_parts)
                else:
                    response_text = " ".join(meaningful_parts)

                if response_text and len(response_text) > 10:
                    property_author = extract_property_author_from_response(response_text) or "Management"
                    response = {
                        "property_response": response_text,
                        "response_date": response_date_rel,
                        "property_author": property_author
                    }
                    return response

        # ============= \"Dear\" format with response date =============
        response_patterns: List[str] = [
            r'\[\["Dear[^"]*"(?:(?:,\s*"[^"]*")*)\]\s*,\s*"([^"]+)"',
            r'\["Dear[^"]*"(?:(?:,\s*"[^"]*")*)\]\s*,\s*"([^"]+)"',
            r'\[\["Thank[^"]*"(?:(?:,\s*"[^"]*")*)\]\s*,\s*"([^"]+)"',
        ]
        for pattern in response_patterns:
            match = re.search(pattern, review_block, re.DOTALL)
            if match:
                response_date_rel = match.group(1)
                response_text_match = re.search(r'\[((?:"[^"]*"(?:,\s*"[^"]*")*))\]\s*,\s*"[^"]+"', review_block)
                if response_text_match:
                    parts_str = response_text_match.group(1)
                    text_parts = re.findall(r'"([^"]*)"', parts_str)
                    meaningful_parts = [p.strip() for p in text_parts if p.strip()]
                    if meaningful_parts:
                        has_original = any('(Original)' in part for part in meaningful_parts)
                        if has_original:
                            response_text = extract_response_original_text(meaningful_parts)
                        else:
                            response_text = " ".join(meaningful_parts)
                        response_text = re.sub(r'\s+', ' ', response_text).strip()
                        property_author = extract_property_author_from_response(response_text) or "Management"
                        response = {
                            "property_response": response_text,
                            "response_date": response_date_rel,
                            "property_author": property_author
                        }
                        return response

        return response

    def filter_valid_review(review_obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Filter review object - only keep if it has required fields."""
        if 'reviewer_id' in review_obj and review_obj['reviewer_id']:
            review_obj['author_id'] = review_obj.pop('reviewer_id')
        if 'reviewer_name' in review_obj and review_obj['reviewer_name']:
            review_obj['author_name'] = review_obj.pop('reviewer_name')
        
        required_fields: List[str] = ['review_id', 'author_id', 'author_name', 'relative_date']
        missing_fields: List[str] = []
        for field in required_fields:
            if field not in review_obj or review_obj[field] is None or review_obj[field] == "":
                missing_fields.append(field)
        
        if missing_fields:
            return None
        
        if 'sub_ratings' in review_obj and (not review_obj['sub_ratings'] or len(review_obj['sub_ratings']) == 0):
            del review_obj['sub_ratings']
        
        if 'property_response' not in review_obj or not review_obj['property_response']:
            review_obj.pop('property_response', None)
            review_obj.pop('response_date', None)
            review_obj.pop('property_author', None)
            review_obj.pop('response_relative_date', None)
        
        if 'review_count' in review_obj and (review_obj['review_count'] == 0 or review_obj['review_count'] is None):
            del review_obj['review_count']
        
        if 'rating' in review_obj and review_obj['rating'] == 0:
            if 'sub_ratings' in review_obj and review_obj['sub_ratings']:
                first_rating = next(iter(review_obj['sub_ratings'].values()))
                if first_rating and first_rating > 0:
                    review_obj['rating'] = first_rating
        
        review_obj = {k: v for k, v in review_obj.items() if v is not None}
        
        return review_obj

    def extract_language_from_section(section: str) -> str:
        """Extract language from section. Default to 'English' if not found."""
        lang_map: Dict[str, str] = {
            'ja': 'Japanese', 'Japanese': 'Japanese',
            'nl': 'Dutch', 'Dutch': 'Dutch',
            'en': 'English', 'English': 'English',
            'es': 'Spanish', 'Spanish': 'Spanish',
            'fr': 'French', 'French': 'French',
            'de': 'German', 'German': 'German',
            'ar': 'Arabic', 'Arabic': 'Arabic',
        }
        
        lang_match = re.search(r'\["([a-z]{2})"', section)
        if lang_match:
            lang_code = lang_match.group(1)
            if lang_code in lang_map:
                return lang_map[lang_code]
        
        for key, value in lang_map.items():
            if key in section or value in section:
                return value
        
        return "English"

    def extract_author_images(review_block: str) -> List[str]:
        """Extract images uploaded by the reviewer (grass-cs images)."""
        images: List[str] = []
        
        grass_pattern = r'\["https://lh3\.googleusercontent\.com/grass-cs/[^"]+"\s*,\s*\d+,\s*\d+'
        grass_matches = re.findall(grass_pattern, review_block)
        
        for match in grass_matches:
            url_match = re.search(r'"([^"]+)"', match)
            if url_match:
                url = url_match.group(1)
                url = url.replace('\\u003d', '=').replace('\\u0026', '&')
                url = re.sub(r'=s\d+(-[a-z0-9]+)?', '', url)
                if url and url not in images:
                    images.append(url)
        
        return images

    def extract_author_image_logo(review_block: str) -> Optional[str]:
        """Extract the reviewer's profile image."""
        # Pattern 1: Standard pattern for profile images
        profile_pattern = r'"https://lh3\.googleusercontent\.com/a/[^"]+"'
        match = re.search(profile_pattern, review_block)
        if match:
            url = match.group(0).strip('"')
            url = url.replace('\\\\u003d', '=').replace('\\\\u0026', '&')
            url = url.replace('\\u003d', '=').replace('\\u0026', '&')
            # Clean up any remaining escapes
            url = re.sub(r'\\\\', '', url)
            return url
        
        # Pattern 2: Handle escaped backslashes (\\u003d format)
        profile_pattern2 = r'https://lh3\.googleusercontent\.com/a/[^"\\\\]+'
        match = re.search(profile_pattern2, review_block)
        if match:
            url = match.group(0)
            url = url.replace('\\\\u003d', '=').replace('\\\\u0026', '&')
            url = url.replace('\\u003d', '=').replace('\\u0026', '&')
            # Clean up any remaining escapes
            url = re.sub(r'\\\\', '', url)
            return url
        
        # Pattern 3: Look for profile image in the array format
        # Pattern: ["https://lh3.googleusercontent.com/a-/...", 40, 40]
        profile_pattern3 = r'\[\s*"https://lh3\.googleusercontent\.com/a/[^"]+"\s*,\s*\d+,\s*\d+\s*\]'
        match = re.search(profile_pattern3, review_block)
        if match:
            url_match = re.search(r'"([^"]+)"', match.group(0))
            if url_match:
                url = url_match.group(1)
                url = url.replace('\\\\u003d', '=').replace('\\\\u0026', '&')
                url = url.replace('\\u003d', '=').replace('\\u0026', '&')
                url = re.sub(r'\\\\', '', url)
                return url
        
        # Pattern 4: Look for profile image with specific format from your example
        # "https://lh3.googleusercontent.com/a-/ALV-UjXdh5Jv9vYrjsDqWQ94NoQvg40YcLqBsf_MBMgAB3k-fhUQtwg\\\\u003ds40-c-rp-mo-ba12-br100"
        profile_pattern4 = r'https://lh3\.googleusercontent\.com/a/[^"\\]+(?:\\\\u003d[^"\\]+)?'
        match = re.search(profile_pattern4, review_block)
        if match:
            url = match.group(0)
            url = url.replace('\\\\u003d', '=').replace('\\\\u0026', '&')
            url = url.replace('\\u003d', '=').replace('\\u0026', '&')
            url = re.sub(r'\\\\', '', url)
            return url
        
        # Pattern 5: Generic pattern for any lh3.googleusercontent.com image
        profile_pattern5 = r'https://lh3\.googleusercontent\.com/[^\s"\'\\\\]+'
        match = re.search(profile_pattern5, review_block)
        if match:
            url = match.group(0)
            # Only return if it looks like a profile image (contains /a/ or /a-/)
            if '/a/' in url or '/a-/' in url:
                url = url.replace('\\\\u003d', '=').replace('\\\\u0026', '&')
                url = url.replace('\\u003d', '=').replace('\\u0026', '&')
                url = re.sub(r'\\\\', '', url)
                return url
        
        return None

    def extract_details_ocp93e(review_block: str) -> Dict[str, Any]:
        """Extract all details from ocp93e format."""
        details: Dict[str, Any] = {}
        
        # Original extraction for ocp93e format
        highlights_match = re.search(r'\["Hotel highlights"\s*,\s*\[(.*?)\]\]', review_block)
        if highlights_match:
            highlights_str: str = highlights_match.group(1)
            highlights: List[str] = re.findall(r'"([^"]+)"', highlights_str)
            if highlights:
                details["Hotel highlights"] = " · ".join(h for h in highlights if h)
        
        detail_pattern = r'\[\s*\["([^"]+)"\s*,\s*"([^"]+)"\s*\]\s*\]'
        detail_matches: List[Tuple[str, str]] = re.findall(detail_pattern, review_block)
        
        detail_pattern2 = r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\]'
        detail_matches2: List[Tuple[str, str]] = re.findall(detail_pattern2, review_block)
        
        all_matches: List[Tuple[str, str]] = detail_matches + detail_matches2
        
        detail_categories: List[str] = [
            "Rooms", "Nearby activities", "Safety", "Walkability", 
            "Food and drinks", "Noteworthy details", "Cleanliness",
            "Service", "Value", "Location", "Atmosphere", "Amenities",
            "Bathroom", "Bed", "Hotel highlights"
        ]
        
        for match in all_matches:
            if len(match) >= 2:
                key: str = match[0]
                value: str = match[1]
                if key in detail_categories:
                    details[key] = value
        
        # ============= FALLBACK: Extract details from qv9Egd format =============
        # If no details were found, try the new format
        if not details:
            # Pattern for qv9Egd format: ["HOTELS_TIPS_TOPICS_ROOMS"],"Rooms",...,["value"]
            tip_patterns = [
                (r'\["HOTELS_TIPS_TOPICS_ROOMS"\],\s*"Rooms",\s*null,\s*null,\s*"[^"]+",\s*"Rooms",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', "Rooms"),
                (r'\["HOTELS_TIPS_TOPICS_FOOD_AND_DRINKS"\],\s*"Food\\u0026drinks",\s*null,\s*null,\s*"[^"]+",\s*"Food\\u0026drinks",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', "Food and drinks"),
                (r'\["HOTELS_TIPS_TOPICS_NOTEWORTHY_DETAILS"\],\s*"Noteworthy details",\s*null,\s*null,\s*"[^"]+",\s*"Noteworthy details",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', "Noteworthy details"),
                (r'\["HOTELS_TIPS_TOPICS_NEARBY_ACTIVITIES"\],\s*"Nearby activities",\s*null,\s*null,\s*"[^"]+",\s*"Nearby activities",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', "Nearby activities"),
                (r'\["HOTELS_TIPS_TOPICS_SAFETY"\],\s*"Safety",\s*null,\s*null,\s*"[^"]+",\s*"Safety",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', "Safety"),
                (r'\["HOTELS_TIPS_TOPICS_WALKABILITY"\],\s*"Walkability",\s*null,\s*null,\s*"[^"]+",\s*"Walkability",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', "Walkability"),
                (r'\["HOTELS_TIPS_TOPICS_CLEANLINESS"\],\s*"Cleanliness",\s*null,\s*null,\s*"[^"]+",\s*"Cleanliness",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', "Cleanliness"),
                (r'\["HOTELS_TIPS_TOPICS_AMENITIES"\],\s*"Amenities",\s*null,\s*null,\s*"[^"]+",\s*"Amenities",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', "Amenities"),
                (r'\["HOTELS_TIPS_TOPICS_BATHROOM"\],\s*"Bathroom",\s*null,\s*null,\s*"[^"]+",\s*"Bathroom",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', "Bathroom"),
                (r'\["HOTELS_TIPS_TOPICS_BED"\],\s*"Bed",\s*null,\s*null,\s*"[^"]+",\s*"Bed",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', "Bed"),
            ]
            
            for pattern, category in tip_patterns:
                match = re.search(pattern, review_block)
                if match:
                    value = match.group(1)
                    if value and value not in ["null", "Unknown"]:
                        details[category] = value
            
            # Extract Hotel highlights from qv9Egd format
            # Pattern: ["HOTELS_VIBE"],"How would you describe the hotel?",...,[["E:HOTEL_VIBES_QUIET"],"Quiet",...]
            vibe_match = re.search(r'\["HOTELS_VIBE"\],\s*"[^"]+",\s*null,\s*\[(.*?)\],\s*null,\s*"Hotel highlights"', review_block, re.DOTALL)
            if vibe_match:
                vibe_content: str = vibe_match.group(1)
                # Find all vibe entries: ["E:HOTEL_VIBES_QUIET"],"Quiet"
                vibe_entries = re.findall(r'\["E:HOTEL_VIBES_([^"]+)"\],\s*"([^"]+)"', vibe_content)
                if vibe_entries:
                    highlights_list: List[str] = []
                    for _, highlight_name in vibe_entries:
                        if highlight_name and highlight_name not in ["null", "Unknown"]:
                            highlights_list.append(highlight_name)
                    if highlights_list:
                        details["Hotel highlights"] = " · ".join(highlights_list)
            
            # Alternative: Look for vibe entries without the full pattern
            if "Hotel highlights" not in details:
                vibe_alt = re.findall(r'\["E:HOTEL_VIBES_([^"]+)"\],\s*"([^"]+)"', review_block)
                if vibe_alt:
                    highlights_list = []
                    for _, highlight_name in vibe_alt:
                        if highlight_name and highlight_name not in ["null", "Unknown"]:
                            highlights_list.append(highlight_name)
                    if highlights_list:
                        details["Hotel highlights"] = " · ".join(highlights_list)
            
            # Extract from the newer format where details are in a different structure
            # Pattern: ["HOTELS_TIPS_TOPICS_ROOMS"],"Rooms",["value"]
            alt_tip_pattern = r'\["HOTELS_TIPS_TOPICS_([^"]+)"\],\s*"([^"]+)",\s*null,\s*null,\s*"[^"]+",\s*"([^"]+)",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]'
            alt_matches = re.findall(alt_tip_pattern, review_block)
            for match in alt_matches:
                if len(match) >= 4:
                    category = match[1]
                    value = match[3]
                    if value and value not in ["null", "Unknown"]:
                        details[category] = value
            
            # Extract Room and other details from the array format
            room_pattern = r'\["Rooms",\s*"([^"]+)"\]'
            room_match = re.search(room_pattern, review_block)
            if room_match and "Rooms" not in details:
                details["Rooms"] = room_match.group(1)
            
            # Extract Walkability
            walk_pattern = r'\["Walkability",\s*"([^"]+)"\]'
            walk_match = re.search(walk_pattern, review_block)
            if walk_match and "Walkability" not in details:
                details["Walkability"] = walk_match.group(1)
            
            # Extract Noteworthy details
            noteworthy_pattern = r'\["Noteworthy details",\s*"([^"]+)"\]'
            noteworthy_match = re.search(noteworthy_pattern, review_block)
            if noteworthy_match and "Noteworthy details" not in details:
                details["Noteworthy details"] = noteworthy_match.group(1)
        
        return details

    def extract_trip_type(review_block: str) -> Optional[str]:
        """Extract trip type from review block with multiple patterns for old data.
        
        Combines both the trip type (e.g. Vacation) AND the travel group 
        (e.g. Family, Couple, Solo, Business, Friends) when both are present.
        """
        found_types: List[str] = []
        
        # ============= TRIP TYPE (E:HOTELS_TRIP_TYPE_*) =============
        trip_type_patterns: List[str] = [
            r'\["HOTELS_PILOT_TRIP_TYPE"\],\s*"([^"]+)"\s*,\s*\[\[\["E:HOTELS_TRIP_TYPE_([^"]+)"\]\s*,\s*"([^"]+)"',
            r'\[\[\["E:HOTELS_TRIP_TYPE_([^"]+)"\]\s*,\s*"([^"]+)"',
            r'\["E:HOTELS_TRIP_TYPE_([^"]+)"\]\s*,\s*"([^"]+)"',
        ]
        for pattern in trip_type_patterns:
            match = re.search(pattern, review_block)
            if match:
                # Different patterns have different group positions
                if len(match.groups()) == 3:
                    value = match.group(3)
                else:
                    value = match.group(2)
                if value and value not in found_types:
                    found_types.append(value)
                break
        
        # ============= TRAVEL GROUP (E:HOTELS_TRAVEL_GROUP_*) =============
        travel_group_patterns: List[str] = [
            r'\["HOTELS_PILOT_TRAVEL_GROUP_TYPE"\],\s*"([^"]+)"\s*,\s*\[\[\["E:HOTELS_TRAVEL_GROUP_([^"]+)"\]\s*,\s*"([^"]+)"',
            r'\[\[\["E:HOTELS_TRAVEL_GROUP_([^"]+)"\]\s*,\s*"([^"]+)"',
            r'\["E:HOTELS_TRAVEL_GROUP_([^"]+)"\]\s*,\s*"([^"]+)"',
        ]
        for pattern in travel_group_patterns:
            match = re.search(pattern, review_block)
            if match:
                if len(match.groups()) == 3:
                    value = match.group(3)
                else:
                    value = match.group(2)
                if value and value not in found_types:
                    found_types.append(value)
                break
        
        # If we found at least one, join them
        if found_types:
            return ", ".join(found_types)
        
        # ============= FALLBACK: Infer from review text keywords =============
        review_text: Optional[str] = None
        text_patterns: List[str] = [
            r'\[\["((?:[^"\\]|\\.)*)",\s*null,\s*\[\d+,\s*\d+\]\]',
            r'\[1,\s*"((?:[^"\\]|\\.)*)"',
            r'\["((?:[^"\\]|\\.)*)",\s*null,\s*\[\d+,\s*\d+\]\]',
        ]
        for pattern in text_patterns:
            text_match = re.search(pattern, review_block)
            if text_match:
                review_text = text_match.group(1)
                break
        
        if review_text:
            normalized: str = review_text.lower()
            normalized = normalized.replace('\\u003cbr\\u003e', ' ')
            normalized = normalized.replace('<br>', ' ')
            normalized = normalized.replace('\\n', ' ')
            normalized = re.sub(r'\s+', ' ', normalized)
            
            trip_type_keywords: List[Tuple[str, List[str]]] = [
                ("Business", [
                    "business trip", "business stay", "business travel",
                    "work trip", "for work", "on business", "business meeting",
                    "business conference", "corporate stay", "work stay",
                    "business visitor", "attending a conference", "for business",
                ]),
                ("Family", [
                    "family trip", "family vacation", "with family",
                    "with my family", "with the family", "with kids",
                    "with the kids", "with children", "with my children",
                    "family stay", "family holiday", "brought the kids",
                    "brought my kids", "our kids", "the kids loved",
                ]),
                ("Couple", [
                    "couple", "my partner", "with my partner", "with my wife",
                    "with my husband", "with my fianc", "romantic getaway",
                    "romantic trip", "anniversary", "honeymoon",
                    "with my girlfriend", "with my boyfriend",
                ]),
                ("Solo", [
                    "solo trip", "solo travel", "solo stay", "travelling alone",
                    "traveling alone", "on my own", "by myself", "i was alone",
                    "solo traveller", "solo traveler", "solo visitor",
                ]),
                ("Friends", [
                    "with friends", "with my friends", "group of friends",
                    "friend trip", "friends trip", "weekend with friends",
                    "girls trip", "boys trip", "friends getaway",
                ]),
            ]
            
            for trip_type, keywords in trip_type_keywords:
                for keyword in keywords:
                    if keyword in normalized:
                        return trip_type
        
        return None

    def extract_rating(review_block: str) -> int:
        """Extract rating from review block with multiple patterns for old data."""
        rating: int = 5
        
        # ============= NEW: Pattern for qv9Egd format =============
        # Look for [[5],null,null,...] pattern at the start of the review
        # The rating is the number inside the first brackets
        qv9_pattern = r'\[\s*\[(\d+)\]\s*,\s*null\s*,\s*null'
        qv9_match = re.search(qv9_pattern, review_block)
        if qv9_match:
            try:
                return int(qv9_match.group(1))
            except:
                pass
        
        # Pattern 1: Original pattern - look for ] , [number]
        rating_match = re.search(r'\]\s*,\s*\[(\d+)\]', review_block)
        if rating_match:
            try:
                return int(rating_match.group(1))
            except:
                pass
        
        # Pattern 2: Look for [[number], null, number] pattern
        rating_match2 = re.search(r'\[\[(\d+)\],\s*null,\s*(\d+)', review_block)
        if rating_match2:
            try:
                return int(rating_match2.group(1))
            except:
                pass
        
        # Pattern 3: Look for , [number] , null, 1, null, 0
        rating_match3 = re.search(r',\s*\[(\d+)\]\s*,\s*null,\s*1,\s*null,\s*0', review_block)
        if rating_match3:
            try:
                return int(rating_match3.group(1))
            except:
                pass
        
        # Pattern 4: Look for float rating pattern
        float_match = re.search(r'null,\s*1,\s*null,\s*([0-9.]+)\]', review_block)
        if float_match:
            try:
                return int(float(float_match.group(1)))
            except:
                pass
        
        # Pattern 5: Look for rating in the structure [[5], null, null, null, ...]
        # This is more specific to the qv9Egd format
        rating_pattern5 = r'\[\s*\[(\d+)\]\s*,\s*null'
        match5 = re.search(rating_pattern5, review_block)
        if match5:
            try:
                return int(match5.group(1))
            except:
                pass
        
        # Pattern 6: Look for rating as [5] pattern anywhere
        rating_pattern6 = r'\[(\d+)\]\s*,\s*null\s*,\s*null\s*,\s*null\s*,\s*null\s*,\s*null'
        match6 = re.search(rating_pattern6, review_block)
        if match6:
            try:
                return int(match6.group(1))
            except:
                pass
        
        return rating

    def extract_review_text(review_block: str) -> Optional[str]:
        """Extract review text from review block with multiple patterns for old data."""

        escaped_patterns: List[str] = [
            # Multi-nested: [[[1, "text", null, "translated", false, true]]]
            r'\[\[\[1,\s*"((?:[^"\\]|\\.)*)"',
            # [[\"text\", null, [0, N]]]
            r'\[\["((?:[^"\\]|\\.)*)",\s*null,\s*\[\d+,\s*\d+\]\]',
            # [\"text\", null, [0, N]]
            r'\["((?:[^"\\]|\\.)*)",\s*null,\s*\[\d+,\s*\d+\]\]',
            # [1, "text", ...]
            r'\[1,\s*"((?:[^"\\]|\\.)*)"',
        ]
        
        for pattern in escaped_patterns:
            match = re.search(pattern, review_block)
            if match:
                text = match.group(1)
                # Unescape the captured text before processing
                text = text.replace('\\"', '"')
                text = text.replace('\\/', '/')
                text = text.replace('\\u003cbr\\u003e', '<br>')
                text = text.replace('\\u003c', '<').replace('\\u003e', '>')
                text = text.replace('\\u0026', '&')
                text = text.replace('\\n', '\n')
                text = text.replace('\\t', '\t')
                # Now extract the original from translation
                return extract_original_text(text)
        
        return None    

    #  ====== Main normalisers ======.
    def extract_reviews_maps_ugc(file_content: str) -> List[Dict[str, Any]]:
        """Extract reviews from MapsUgcPostService format using universal marker."""
        reviews_list: List[Dict[str, Any]] = []
        seen_reviews: set[str] = set()
        
        content: str = unescape_data(file_content)
        
        review_starts = re.finditer(r'\[\s*"0x0:0', content)
        start_positions: List[int] = [m.start() for m in review_starts]
        
        for idx, start_pos in enumerate(start_positions, 1):
            if idx < len(start_positions):
                end_pos: int = start_positions[idx]
            else:
                end_pos: int = len(content)
            
            review_block: str = content[start_pos:end_pos]
            context_start: int = max(0, start_pos - 500)
            context: str = content[context_start:start_pos]
            
            review_id_match = re.search(r'\["([^"]+)"\s*,\s*\["0x0:0', review_block)
            review_id: Optional[str] = review_id_match.group(1) if review_id_match else None
            
            if not review_id:
                review_id_match = re.search(r'\["([^"]+)"\s*,\s*\["0x0:0', context)
                review_id = review_id_match.group(1) if review_id_match else None
            
            reviewer_id_match = re.search(r'/contrib/(\d+)/reviews', review_block)
            reviewer_id: Optional[str] = reviewer_id_match.group(1) if reviewer_id_match else None
            
            if not reviewer_id:
                reviewer_id_match = re.search(r'/contrib/(\d+)/reviews', context)
                reviewer_id = reviewer_id_match.group(1) if reviewer_id_match else None
            
            reviewer_name_match = re.search(r'\["([^"]+)",\s*"https://lh3\.googleusercontent\.com/', review_block)
            reviewer_name: Optional[str] = reviewer_name_match.group(1) if reviewer_name_match else None
            
            if not reviewer_name:
                reviewer_name_match = re.search(r'\["([^"]+)",\s*"https://lh3\.googleusercontent\.com/', context)
                reviewer_name = reviewer_name_match.group(1) if reviewer_name_match else None
            
            author_images: List[str] = extract_author_images(review_block)
            author_image_logo: Optional[str] = extract_author_image_logo(review_block)
            
            url_match = re.search(r'"https://www\.google\.com/maps/contrib/(\d+)/reviews\?hl\\u003den"', review_block)
            author_url: Optional[str] = f"https://www.google.com/maps/contrib/{url_match.group(1)}" if url_match else None
            
            if not author_url and reviewer_id:
                author_url = f"https://www.google.com/maps/contrib/{reviewer_id}"
            
            review_count: int = 0
            count_match = re.search(r'\["(\d+)\s*reviews"', review_block)
            if count_match:
                review_count = int(count_match.group(1))
            else:
                count_match2 = re.search(r'Local Guide · (\d+) reviews', review_block)
                if count_match2:
                    review_count = int(count_match2.group(1))
            
            source_match = re.search(r'\["([^"]+)"\s*,\s*"https://www\.gstatic\.com/images/branding/product/1x/googleg_48dp\.png"', review_block)
            source: str = source_match.group(1) if source_match else "Google"
            
            date_match = re.search(r'null,\s*"([^"]+)"\s*,\s*null,\s*null,\s*null,\s*null,\s*null,\s*null', review_block)
            relative_date: Optional[str] = date_match.group(1) if date_match else None
            if not relative_date or relative_date == "Unknown":
                date_match2 = re.search(r'"([^"]+)"\s*,\s*null,\s*null,\s*null,\s*null,\s*null,\s*null,\s*\["Google"', review_block)
                if date_match2:
                    relative_date = date_match2.group(1)
            
            trip_type: Optional[str] = extract_trip_type(review_block)
            
            sub_ratings: Dict[str, int] = {}
            aspect_pattern = r'\["HOTELS_ASPECT_([^"]+)"\],\s*"([^"]+)",\s*null,\s*null,\s*null,\s*"[^"]+",\s*null,\s*"[^"]+",\s*null,\s*null,\s*null,\s*\[(\d+)\]'
            aspect_matches: List[Tuple[str, str, str]] = re.findall(aspect_pattern, review_block)
            for match in aspect_matches:
                if len(match) >= 3:
                    category: str = match[1]
                    val: int = int(match[2]) if match[2].isdigit() else 0
                    sub_ratings[category] = val
            
            language: str = extract_language_from_section(review_block)
            review_text: Optional[str] = extract_review_text(review_block)
            rating: int = extract_rating(review_block)
            
            details: Dict[str, Any] = {}
            
            vibe_matches = re.findall(r'\["E:HOTEL_VIBES_([^"]+)"\],\s*"([^"]+)"', review_block)
            if vibe_matches:
                highlights: List[str] = []
                for match in vibe_matches:
                    highlight: str = match[1] if match[1] else match[0].replace('_', ' ').title()
                    if highlight:
                        highlights.append(highlight)
                if highlights:
                    details["Hotel highlights"] = " · ".join(highlights)
            
            room_match = re.search(r'\["HOTELS_TIPS_TOPICS_ROOMS"\],\s*"Rooms",\s*null,\s*null,\s*"Tell others about rooms",\s*"Rooms",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', review_block)
            if room_match:
                room_details: str = room_match.group(1)
                if room_details:
                    details["Rooms"] = room_details
            
            food_match = re.search(r'\["HOTELS_TIPS_TOPICS_FOOD_AND_DRINKS"\],\s*"Food \\u0026 drinks",\s*null,\s*null,\s*"Tell others about food and drinks",\s*"Food \\u0026 drinks",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', review_block)
            if food_match:
                food_details: str = food_match.group(1)
                if food_details:
                    details["Food and drinks"] = food_details
            
            noteworthy_match = re.search(r'\["HOTELS_TIPS_TOPICS_NOTEWORTHY_DETAILS"\],\s*"Noteworthy details",\s*null,\s*null,\s*"Tell others about noteworthy details",\s*"Noteworthy details",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', review_block)
            if noteworthy_match:
                noteworthy: str = noteworthy_match.group(1)
                if noteworthy:
                    details["Noteworthy details"] = noteworthy
            
            nearby_match = re.search(r'\["HOTELS_TIPS_TOPICS_NEARBY_ACTIVITIES"\],\s*"Nearby activities",\s*null,\s*null,\s*"Tell others about nearby activities",\s*"Nearby activities",\s*null,\s*"[^"]+",\s*null,\s*null,\s*\["([^"]+)"\]', review_block)
            if nearby_match:
                nearby_details: str = nearby_match.group(1)
                if nearby_details:
                    details["Nearby activities"] = nearby_details
            
            response: Optional[Dict[str, Any]] = None
            response_match = re.search(r'null,\s*null,\s*null,\s*null,\s*null,\s*null,\s*\["([^"]+)"\]', review_block)
            if response_match:
                response_text: str = response_match.group(1)
                if response_text and len(response_text) > 10:
                    response_text = extract_response_original_text([response_text])
                    property_author: Optional[str] = extract_property_author_from_response(response_text)
                    if property_author:
                        response = {
                            "property_response": response_text,
                            "property_author": property_author
                        }
                    else:
                        response = {
                            "property_response": response_text
                        }

            # Extract URLs
            urls: Dict[str, Optional[str]] = extract_review_urls(review_block)

            review_obj: Dict[str, Any] = {
                "review_id": review_id,
                "reviewer_id": reviewer_id,
                "reviewer_name": reviewer_name,
                "author_image_logo": author_image_logo,
                "author_images": author_images if author_images else None,
                "author_url": author_url,
                "source": source,
                "relative_date": relative_date,
                "trip_type": trip_type,
                "rating": rating,
                "sub_ratings": sub_ratings if sub_ratings else None,
                "language": language,
                "review_text": review_text,
                "review_count": review_count if review_count > 0 else None,
                "details": details if details else None,
                "urls": urls,
            }
            
            if response:
                review_obj["property_response"] = response.get("property_response")
                if response.get("property_author"):
                    review_obj["property_author"] = response.get("property_author")
            
            valid_review = filter_valid_review(review_obj)
            if valid_review:
                review_key: Optional[str] = valid_review.get('author_id', valid_review.get('review_id'))
                if review_key and review_key not in seen_reviews:
                    reviews_list.append(valid_review)
                    seen_reviews.add(str(review_key))
        
        return reviews_list

    def extract_reviews_ocp93e(file_content: str) -> List[Dict[str, Any]]:
        """Extract reviews from ocp93e format."""
        reviews_list: List[Dict[str, Any]] = []
        seen_reviews: set[str] = set()
        
        content: str = unescape_data(file_content)
        
        review_sections: List[str] = re.split(r'\["Google",null,\[', content)
        
        for idx, section in enumerate(review_sections[1:], 1):
            section = '["Google",null,[' + section
            
            name_match = re.search(r'\[\["([^"]+)","https://www\.google\.com/maps/contrib/', section)
            reviewer_name: Optional[str] = name_match.group(1) if name_match else None
            
            id_match = re.search(r'/contrib/(\d+)\?', section)
            reviewer_id: Optional[str] = id_match.group(1) if id_match else None
            
            author_images: List[str] = extract_author_images(section)
            author_image_logo: Optional[str] = extract_author_image_logo(section)
            author_url: Optional[str] = f"https://www.google.com/maps/contrib/{reviewer_id}" if reviewer_id else None
            
            date_match = re.search(r'\]\s*,\s*"([^"]+)"\s*,\s*\[', section)
            relative_date: Optional[str] = date_match.group(1) if date_match else None
            
            rating_match = re.search(r'\[\s*(\d+),\s*(\d+)\s*\]', section)
            rating: int = int(rating_match.group(1)) if rating_match else 5
            
            sub_ratings: Dict[str, int] = {}
            sub_match = re.search(r'\[\[1,\[\s*(\d+),\s*(\d+)\s*\]\],\s*\[4,\[\s*(\d+),\s*(\d+)\s*\]\],\s*\[5,\[\s*(\d+),\s*(\d+)\s*\]\]\]', section)
            if sub_match:
                sub_ratings["Rooms"] = int(sub_match.group(1))
                sub_ratings["Service"] = int(sub_match.group(3))
                sub_ratings["Location"] = int(sub_match.group(5))
            else:
                rooms_match = re.search(r'\[1,\[\s*(\d+),\s*(\d+)\s*\]\]', section)
                if rooms_match:
                    sub_ratings["Rooms"] = int(rooms_match.group(1))
                service_match = re.search(r'\[4,\[\s*(\d+),\s*(\d+)\s*\]\]', section)
                if service_match:
                    sub_ratings["Service"] = int(service_match.group(1))
                location_match = re.search(r'\[5,\[\s*(\d+),\s*(\d+)\s*\]\]', section)
                if location_match:
                    sub_ratings["Location"] = int(location_match.group(1))
            
            review_text: Optional[str] = extract_review_text(section)
            language: str = extract_language_from_section(section)
            
            review_count: int = 0
            count_match = re.search(r'Local Guide · (\d+) reviews', section)
            if count_match:
                review_count = int(count_match.group(1))
            
            review_id_match = re.search(r'"Ci9D[^"]+"', section)
            review_id: Optional[str] = review_id_match.group(0).strip('"') if review_id_match else None
            if not review_id:
                review_id_match2 = re.search(r'"ChZD[^"]+"', section)
                if review_id_match2:
                    review_id = review_id_match2.group(0).strip('"')
            
            if not review_id:
                review_id = f"review_{idx}"
            
            source: str = "Google"
            trip_type: Optional[str] = extract_trip_type(section)
            

            response: Optional[Dict[str, Any]] = None
            response = extract_property_response_from_block(section)
            
            details = extract_details_ocp93e(section)
            
            # Extract URLs
            urls: Dict[str, Optional[str]] = extract_review_urls(section)

            review_obj: Dict[str, Any] = {
                "review_id": review_id,
                "reviewer_id": reviewer_id,
                "reviewer_name": reviewer_name,
                "author_image_logo": author_image_logo,
                "author_images": author_images if author_images else None,
                "author_url": author_url,
                "source": source,
                "relative_date": relative_date,
                "trip_type": trip_type,
                "rating": rating,
                "sub_ratings": sub_ratings if sub_ratings else None,
                "language": language,
                "review_text": review_text,
                "review_count": review_count if review_count > 0 else None,
                "details": details if details else None,
                "urls": urls,
            }
            
            if response:
                review_obj["property_response"] = response.get("property_response")
                review_obj["response_relative_date"] = response.get("response_date")
                if response.get("property_author"):
                    review_obj["property_author"] = response.get("property_author")
            
            valid_review = filter_valid_review(review_obj)
            if valid_review:
                review_key: Optional[str] = valid_review.get('author_id', valid_review.get('review_id'))
                if review_key and review_key not in seen_reviews:
                    reviews_list.append(valid_review)
                    seen_reviews.add(str(review_key))
        
        return reviews_list

    def extract_reviews_universal_fallback(file_content: str) -> List[Dict[str, Any]]:
        """Universal fallback parser using the marker '[\"0x0:0' to find review blocks."""
        reviews_list: List[Dict[str, Any]] = []
        seen_reviews: set[str] = set()
        
        content: str = unescape_data(file_content)
        
        marker = r'\[\s*"0x0:0'
        review_starts = re.finditer(marker, content)
        start_positions: List[int] = [m.start() for m in review_starts]
        
        for idx, start_pos in enumerate(start_positions, 1):
            if idx < len(start_positions):
                end_pos: int = start_positions[idx]
            else:
                end_pos: int = len(content)
            
            review_block: str = content[start_pos:end_pos]
            context_start: int = max(0, start_pos - 500)
            context: str = content[context_start:start_pos]
            
            reviewer_name: Optional[str] = None
            name_patterns: List[str] = [
                r'\["([^"]+)",\s*"https://lh3\.googleusercontent\.com/',
                r'\[\["([^"]+)","https://www\.google\.com/maps/contrib/',
            ]
            for pattern in name_patterns:
                match = re.search(pattern, context)
                if match:
                    reviewer_name = match.group(1)
                    break
                match = re.search(pattern, review_block)
                if match:
                    reviewer_name = match.group(1)
                    break
            
            review_id: Optional[str] = None
            id_patterns: List[str] = [r'"Ci9D[^"]+"', r'"ChZD[^"]+"']
            for pattern in id_patterns:
                match = re.search(pattern, review_block)
                if match:
                    review_id = match.group(0).strip('"')
                    break
                match = re.search(pattern, context)
                if match:
                    review_id = match.group(0).strip('"')
                    break
            
            if not review_id:
                review_id = f"review_{idx}"
            
            reviewer_id: Optional[str] = None
            id_patterns = [r'/contrib/(\d+)/reviews', r'/contrib/(\d+)\?', r'maps/contrib/(\d+)']
            for pattern in id_patterns:
                match = re.search(pattern, review_block)
                if match:
                    reviewer_id = match.group(1)
                    break
                match = re.search(pattern, context)
                if match:
                    reviewer_id = match.group(1)
                    break
            
            author_images: List[str] = extract_author_images(review_block)
            author_image_logo: Optional[str] = extract_author_image_logo(review_block)
            author_url: Optional[str] = f"https://www.google.com/maps/contrib/{reviewer_id}" if reviewer_id else None
            
            rating: int = extract_rating(review_block)
            
            sub_ratings: Dict[str, int] = {}
            aspect_pattern = r'\["HOTELS_ASPECT_([^"]+)"\],\s*"([^"]+)",\s*null,\s*null,\s*null,\s*"[^"]+",\s*null,\s*"[^"]+",\s*null,\s*null,\s*null,\s*\[(\d+)\]'
            aspect_matches: List[Tuple[str, str, str]] = re.findall(aspect_pattern, review_block)
            for match in aspect_matches:
                if len(match) >= 3:
                    category: str = match[1]
                    val: int = int(match[2]) if match[2].isdigit() else 0
                    sub_ratings[category] = val
            
            if not sub_ratings:
                rooms_match = re.search(r'\[1,\[\s*(\d+),\s*(\d+)\s*\]\]', review_block)
                if rooms_match:
                    sub_ratings["Rooms"] = int(rooms_match.group(1))
                service_match = re.search(r'\[4,\[\s*(\d+),\s*(\d+)\s*\]\]', review_block)
                if service_match:
                    sub_ratings["Service"] = int(service_match.group(1))
                location_match = re.search(r'\[5,\[\s*(\d+),\s*(\d+)\s*\]\]', review_block)
                if location_match:
                    sub_ratings["Location"] = int(location_match.group(1))
            
            relative_date: Optional[str] = None
            date_patterns: List[str] = [
                r'null,\s*"([^"]+)"\s*,\s*null,\s*null,\s*null,\s*null,\s*null,\s*null',
                r'"([^"]+)"\s*,\s*null,\s*null,\s*null,\s*null,\s*null,\s*null,\s*\["Google"',
                r'\]\s*,\s*"([^"]+)"\s*,\s*\[',
            ]
            for pattern in date_patterns:
                match = re.search(pattern, review_block)
                if match:
                    date_str: str = match.group(1)
                    if date_str and any(word in date_str.lower() for word in ['ago', 'week', 'day', 'month', 'year', 'hour', 'minute']):
                        relative_date = date_str
                        break
            
            review_text: Optional[str] = extract_review_text(review_block)
            language: str = extract_language_from_section(review_block)
            
            review_count: int = 0
            count_match = re.search(r'Local Guide · (\d+) reviews', review_block)
            if count_match:
                review_count = int(count_match.group(1))
            else:
                count_match2 = re.search(r'\["(\d+)\s*reviews"', review_block)
                if count_match2:
                    review_count = int(count_match2.group(1))
            
            source: str = "Google"
            source_match = re.search(r'\["([^"]+)"\s*,\s*"https://www\.gstatic\.com', review_block)
            if source_match:
                source = source_match.group(1)
            
            trip_type: Optional[str] = extract_trip_type(review_block)
            
            response: Optional[Dict[str, Any]] = None
            response = extract_property_response_from_block(review_block)
            
            if not response:
                response_patterns: List[str] = [
                    r'\[\["Dear[^"]*"(?:(?:,\s*"[^"]*")*)\]\s*,\s*"([^"]+)"',
                    r'\["Dear[^"]*"(?:(?:,\s*"[^"]*")*)\]\s*,\s*"([^"]+)"',
                ]
                for pattern in response_patterns:
                    match = re.search(pattern, review_block, re.DOTALL)
                    if match:
                        response_date = match.group(1)
                        response_text_match = re.search(r'\[((?:"[^"]*"(?:,\s*"[^"]*")*))\]\s*,\s*"[^"]+"', review_block)
                        if response_text_match:
                            response_parts_str = response_text_match.group(1)
                            text_parts = re.findall(r'"([^"]*)"', response_parts_str)
                            meaningful_parts = [p.strip() for p in text_parts if p.strip()]
                            if meaningful_parts:
                                has_original = any('(Original)' in part for part in meaningful_parts)
                                if has_original:
                                    response_text = extract_response_original_text(meaningful_parts)
                                else:
                                    response_text = " ".join(meaningful_parts)
                                response_text = re.sub(r'\s+', ' ', response_text).strip()
                                property_author = extract_property_author_from_response(response_text)
                                if property_author:
                                    response = {
                                        "property_response": response_text,
                                        "response_date": response_date,
                                        "property_author": property_author
                                    }
                                else:
                                    response = {
                                        "property_response": response_text,
                                        "response_date": response_date
                                    }
                                break
            
            details = extract_details_ocp93e(review_block)
            
            # Extract URLs
            urls: Dict[str, Optional[str]] = extract_review_urls(review_block)

            review_obj: Dict[str, Any] = {
                "review_id": review_id,
                "reviewer_id": reviewer_id,
                "reviewer_name": reviewer_name,
                "author_image_logo": author_image_logo,
                "author_images": author_images if author_images else None,
                "author_url": author_url,
                "source": source,
                "relative_date": relative_date,
                "trip_type": trip_type,
                "rating": rating,
                "sub_ratings": sub_ratings if sub_ratings else None,
                "language": language,
                "review_text": review_text,
                "review_count": review_count if review_count > 0 else None,
                "details": details if details else None,
                "urls": urls,
            }
            
            if response:
                review_obj["property_response"] = response.get("property_response")
                if response.get("response_date"):
                    review_obj["response_relative_date"] = response.get("response_date")
                if response.get("property_author"):
                    review_obj["property_author"] = response.get("property_author")
            
            valid_review = filter_valid_review(review_obj)
            if valid_review:
                review_key: Optional[str] = valid_review.get('author_id', valid_review.get('review_id'))
                if review_key and review_key not in seen_reviews:
                    reviews_list.append(valid_review)
                    seen_reviews.add(str(review_key))
        
        return reviews_list
    #  ====== Main normalisers ======.

    def convert_relative_dates(reviews_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert relative dates to absolute dates and add createdAt and review_date fields."""
        for review in reviews_list:
            relative_date = review.get('relative_date')
            if relative_date and relative_date not in ["Unknown", "null", "None"]:
                absolute_date = parse_relative_date(str(relative_date))
                if absolute_date:
                    review['date'] = absolute_date.strftime('%Y-%m-%d')
                    review['review_date'] = format_datetime(absolute_date)
                    review['createdAt'] = format_datetime(absolute_date)
                else:
                    review['date'] = None
                    review['review_date'] = None
                    review['createdAt'] = None
            else:
                review['date'] = None
                review['review_date'] = None
                review['createdAt'] = None

            if 'relative_date' in review:
                del review['relative_date']

            # ============= Response date handling =============
            response_relative_date = review.get('response_relative_date')
            if response_relative_date and response_relative_date not in ["Unknown", "null", "None"]:
                # Check if it's an ISO date (already formatted)
                if isinstance(response_relative_date, str) and response_relative_date.startswith('20') and 'T' in response_relative_date:
                    review['response_date'] = response_relative_date
                # Check if it's an epoch timestamp (all digits, length >= 13)
                elif isinstance(response_relative_date, str) and response_relative_date.isdigit() and len(response_relative_date) >= 13:
                    try:
                        epoch_us = int(response_relative_date)
                        dt = datetime.fromtimestamp(epoch_us / 1_000_000)
                        review['response_date'] = format_datetime(dt)
                    except Exception:
                        review['response_date'] = None
                else:
                    absolute_date = parse_relative_date(str(response_relative_date))
                    if absolute_date:
                        review['response_date'] = format_datetime(absolute_date)
                    else:
                        review['response_date'] = None
            else:
                review['response_date'] = None

            if 'response_relative_date' in review:
                del review['response_relative_date']

        return reviews_list

    def extract_reviews_ocp93e_v2(file_content: str) -> List[Dict[str, Any]]:
        """Extract reviews from ocp93e format with enhanced pattern matching for the newer format."""

        reviews_list: List[Dict[str, Any]] = []
        seen_reviews: set[str] = set()
        
        content: str = unescape_data(file_content)
        
        # Split by the pattern that starts each review: ["Google",null,[
        review_sections: List[str] = re.split(r'\["Google",null,\[', content)
        
        for idx, section in enumerate(review_sections[1:], 1):
            section = '["Google",null,[' + section
            
            # Extract reviewer name - try multiple patterns
            reviewer_name: Optional[str] = None
            name_patterns: List[str] = [
                r'\[\["([^"]+)","https://www\.google\.com/maps/contrib/',
                r'\[\["([^"]+)","https://lh3\.googleusercontent\.com/',
                r'"([^"]+)",\s*"https://www\.google\.com/maps/contrib/',
            ]
            for pattern in name_patterns:
                match = re.search(pattern, section)
                if match:
                    reviewer_name = match.group(1)
                    break
            
            # Extract reviewer ID
            reviewer_id: Optional[str] = None
            id_patterns: List[str] = [
                r'/contrib/(\d+)\?',
                r'maps/contrib/(\d+)',
            ]
            for pattern in id_patterns:
                match = re.search(pattern, section)
                if match:
                    reviewer_id = match.group(1)
                    break
            
            # Extract author images
            author_images: List[str] = extract_author_images(section)
            author_image_logo: Optional[str] = extract_author_image_logo(section)
            author_url: Optional[str] = f"https://www.google.com/maps/contrib/{reviewer_id}" if reviewer_id else None
            
            # Extract relative date
            relative_date: Optional[str] = None
            date_patterns: List[str] = [
                r'\]\s*,\s*"([^"]+)"\s*,\s*\[',
                r'"([^"]+)"\s*,\s*\[',
                r'null,\s*"([^"]+)"\s*,\s*null',
            ]
            for pattern in date_patterns:
                match = re.search(pattern, section)
                if match:
                    date_str = match.group(1)
                    if date_str and any(word in date_str.lower() for word in ['ago', 'week', 'day', 'month', 'year', 'hour', 'minute']):
                        relative_date = date_str
                        break
            
            # Extract rating
            rating: int = 5
            rating_patterns: List[str] = [
                r'\[\s*(\d+),\s*(\d+)\s*\]',
                r',\s*\[(\d+)\]\s*,\s*null',
                r'\[\[(\d+)\],\s*null',
            ]
            for pattern in rating_patterns:
                match = re.search(pattern, section)
                if match:
                    try:
                        rating = int(match.group(1))
                        break
                    except:
                        pass
            
            # Extract sub-ratings
            sub_ratings: Dict[str, int] = {}
            sub_match = re.search(r'\[\[1,\[\s*(\d+),\s*(\d+)\s*\]\],\s*\[4,\[\s*(\d+),\s*(\d+)\s*\]\],\s*\[5,\[\s*(\d+),\s*(\d+)\s*\]\]\]', section)
            if sub_match:
                sub_ratings["Rooms"] = int(sub_match.group(1))
                sub_ratings["Service"] = int(sub_match.group(3))
                sub_ratings["Location"] = int(sub_match.group(5))
            else:
                # Try individual patterns
                for aspect, pattern in [("Rooms", r'\[1,\[\s*(\d+),\s*(\d+)\s*\]\]'), 
                                    ("Service", r'\[4,\[\s*(\d+),\s*(\d+)\s*\]\]'),
                                    ("Location", r'\[5,\[\s*(\d+),\s*(\d+)\s*\]\]')]:
                    match = re.search(pattern, section)
                    if match:
                        sub_ratings[aspect] = int(match.group(1))
            
            # Extract review text
            review_text: Optional[str] = None
            text_patterns: List[str] = [
                r'\[\["([^"]+)",\s*null,\s*\[\d+,\s*\d+\]\]',
                r'\[1,\s*"([^"]+)"',
                r'\["([^"]+)",\s*null,\s*\[\d+,\s*\d+\]\]',
                r'\[\[\[1,\s*"([^"]+)"',
            ]
            for pattern in text_patterns:
                match = re.search(pattern, section)
                if match:
                    review_text = extract_original_text(match.group(1))
                    break
            
            # Extract language
            language: str = extract_language_from_section(section)
            
            # Extract review count
            review_count: int = 0
            count_match = re.search(r'Local Guide · (\d+) reviews', section)
            if count_match:
                review_count = int(count_match.group(1))
            
            # Extract review ID
            review_id: Optional[str] = None
            id_patterns = [r'"Ci9D[^"]+"', r'"ChZD[^"]+"', r'"Ci9DQUlR[^"]+"']
            for pattern in id_patterns:
                match = re.search(pattern, section)
                if match:
                    review_id = match.group(0).strip('"')
                    break
            
            if not review_id:
                review_id = f"review_{idx}"
            
            source: str = "Google"
            
            # Extract trip type
            trip_type: Optional[str] = extract_trip_type(section)
            
            # Extract property response
            response: Optional[Dict[str, Any]] = None
            response = extract_property_response_from_block(section)
            
            # Extract details from the new format
            details: Dict[str, Any] = {}
            
            # Extract hotel highlights from the new format
            highlights_match = re.search(r'\["Hotel highlights"\s*,\s*\[(.*?)\]\]', section)
            if highlights_match:
                highlights_str: str = highlights_match.group(1)
                highlights: List[str] = re.findall(r'"([^"]+)"', highlights_str)
                if highlights:
                    details["Hotel highlights"] = " · ".join(h for h in highlights if h)
            
            # Extract other details from the new format
            detail_patterns = [
                r'\[\["([^"]+)"\s*,\s*"([^"]+)"\s*\]\s*\]',
                r'\["([^"]+)"\s*,\s*"([^"]+)"\s*\]',
            ]
            for pattern in detail_patterns:
                matches = re.findall(pattern, section)
                for match in matches:
                    if len(match) >= 2:
                        key = match[0]
                        value = match[1]
                        if key in ["Rooms", "Nearby activities", "Safety", "Walkability", "Food and drinks", 
                                "Noteworthy details", "Cleanliness", "Service", "Value", "Location", 
                                "Atmosphere", "Amenities", "Bathroom", "Bed"]:
                            details[key] = value
            
            # Extract URLs
            urls: Dict[str, Optional[str]] = extract_review_urls(section)

            # Build review object
            review_obj: Dict[str, Any] = {
                "review_id": review_id,
                "reviewer_id": reviewer_id,
                "reviewer_name": reviewer_name,
                "author_image_logo": author_image_logo,
                "author_images": author_images if author_images else None,
                "author_url": author_url,
                "source": source,
                "relative_date": relative_date,
                "trip_type": trip_type,
                "rating": rating,
                "sub_ratings": sub_ratings if sub_ratings else None,
                "language": language,
                "review_text": review_text,
                "review_count": review_count if review_count > 0 else None,
                "details": details if details else None,
                "urls": urls,
            }
            
            if response:
                review_obj["property_response"] = response.get("property_response")
                review_obj["response_relative_date"] = response.get("response_date")
                if response.get("property_author"):
                    review_obj["property_author"] = response.get("property_author")
            
            valid_review = filter_valid_review(review_obj)
            if valid_review:
                review_key: Optional[str] = valid_review.get('author_id', valid_review.get('review_id'))
                if review_key and review_key not in seen_reviews:
                    reviews_list.append(valid_review)
                    seen_reviews.add(str(review_key))
        
        return reviews_list

    def process_response_content(content: str) -> List[Dict[str, Any]]:
        """
        Process the response content and extract reviews using the appropriate parser.
        
        Args:
            content: The raw response string to process
            
        Returns:
            List of extracted review dictionaries
        """
        format_type: str = detect_format(content)
        
        extracted_reviews: List[Dict[str, Any]] = []
        
        if format_type == 'ocp93e':
            # Try both ocp93e parsers
            extracted_reviews = extract_reviews_ocp93e(content)
            if not extracted_reviews:
                extracted_reviews = extract_reviews_ocp93e_v2(content)
        elif format_type == 'maps_ugc':
            extracted_reviews = extract_reviews_maps_ugc(content)
        else:
            extracted_reviews = extract_reviews_maps_ugc(content)
            if not extracted_reviews:
                extracted_reviews = extract_reviews_ocp93e_v2(content)
        
        if not extracted_reviews:
            extracted_reviews = extract_reviews_universal_fallback(content)
        
        return extracted_reviews
    # ==================== MAIN PROCESSING ====================

    def main_processing(response: str) -> List[Review]:
        """Main processing function that orchestrates the entire review extraction pipeline."""
        reviews: List[Review] = []
        
        # Process the response content
        extracted_reviews: List[Dict[str, Any]] = process_response_content(response)
        
        # Convert relative dates
        extracted_reviews = convert_relative_dates(extracted_reviews)
        
        # Clean null values
        extracted_reviews = clean_null_values(extracted_reviews)
        
        # Convert to Review type with ALL fields
        for review in extracted_reviews:
            review_obj: Review = {
                "review_id": review.get("review_id", ""),
                "author_name": review.get("author_name", review.get("reviewer_name", "")),
                "author_id": review.get("author_id", review.get("reviewer_id")),
                "author_image_logo": review.get("author_image_logo"),
                "author_images": review.get("author_images"),
                "author_url": review.get("author_url"),
                "rating": float(review.get("rating", 0)),
                "sub_ratings": review.get("sub_ratings"),
                "review_text": review.get("review_text", ""),
                "published_at": review.get("review_date", review.get("date", "")),
                "date": review.get("date"),
                "review_date": review.get("review_date"),
                "createdAt": review.get("createdAt"),
                "source": review.get("source", "Google"),
                "language": review.get("language", "English"),
                "trip_type": review.get("trip_type"),
                "review_count": review.get("review_count"),
                "details": review.get("details"),
                "property_response": review.get("property_response"),
                "property_author": review.get("property_author"),
                "response_date": review.get("response_date"),
                "urls": review.get("urls"),
            }
            reviews.append(review_obj)
            
        return reviews

    return main_processing(response)
