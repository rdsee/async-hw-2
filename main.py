import time
from email import header

import aiohttp
import asyncio
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)

logger = logging.getLogger(__name__)


def log_section(title: str) -> None:
    """Print a visible separator for a demo section."""
    logger.info("")
    logger.info("=" * 78)
    logger.info(title)
    logger.info("=" * 78)


class HTMLParser:
    def __init__(self):
        pass

    async def parse_html(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        metadata = self.extract_metadata(soup)
        text = self.extract_text(soup)
        links = self.extract_links(soup, url)
        images = self.extract_images(soup)
        headings = self.extract_headings(soup)
        tables = self.extract_tables(soup)
        lists = self.extract_lists(soup)

        return {
            "url": url,
            "title": metadata["title"],
            "metadata": metadata,
            "text": text,
            "links": links,
            "images": images,
            "headings": headings,
            "tables": tables,
            "lists": lists
        }

    def extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        links_tags = soup.find_all("a", href=True)
        links = []
        seen = set()

        for i in links_tags:
            link = i.get("href", "").strip()

            if not link:
                continue

            if link.startswith(("#", "mailto:", "javascript:", "tel:")):
                continue

            absolute_url = urljoin(base_url, link)
            absolute_url, _ = urldefrag(absolute_url)

            parsed_url = urlparse(absolute_url)

            if parsed_url.scheme not in ("http", "https"):
                continue

            if not parsed_url.netloc:
                continue

            if absolute_url not in seen:
                seen.add(absolute_url)
                links.append(absolute_url)

        return links

    def extract_text(self, soup: BeautifulSoup, selector: str = None) -> str:
        if selector:
            target = soup.select_one(selector)

            if target is None:
                logger.warning("Selector not found: %s", selector)
                return ""
        else:
            target = soup

        return target.get_text(" ", strip=True)

    def extract_metadata(self, soup: BeautifulSoup) -> dict:
        title_tag = soup.find("title")
        if title_tag is not None:
            title = title_tag.get_text(strip=True)
        else:
            logger.warning("Title not found")
            title = ""

        description_tag = soup.find("meta", attrs={"name":"description"})
        if description_tag is not None:
            description = description_tag.get("content", "")
        else:
            logger.warning("Description not found")
            description = ""

        keywords_tag = soup.find("meta", attrs={"name": "keywords"})
        if keywords_tag is not None:
            keywords = keywords_tag.get("content", "")
        else:
            logger.warning("Keyword not found")
            keywords = ""

        return {
            "title": title,
            "description": description,
            "keywords": keywords,
        }

    def extract_images(self, soup: BeautifulSoup) -> list[dict]:
        images = []
        images_tag = soup.find_all("img", src=True)

        if not images_tag:
            logger.warning("Image not found")

        for img in images_tag:
            src = img.get("src")
            alt = img.get("alt")

            if alt is None:
                alt = ""

            img_dict = {"src": src, "alt": alt}
            images.append(img_dict)

        return images

    def extract_headings(self, soup: BeautifulSoup) -> list[dict]:
        heading = []

        heading_tags = soup.find_all(["h1", "h2", "h3"])

        for head in heading_tags:
            text = head.get_text(" ", strip=True)

            head_dict = {
                "level": head.name,
                "text": text
            }

            heading.append(head_dict)
        return heading

    def extract_tables(self, soup: BeautifulSoup) -> list[dict]:
        tables = []

        for table_tag in soup.find_all("table"):
            headers = []
            rows = []

            for row_tag in table_tag.find_all("tr"):
                cell_tags = row_tag.find_all(["th", "td"])

                row_values = [
                    cell.get_text(" ", strip=True)
                    for cell in cell_tags
                ]

                if not row_values:
                    continue

                header_tags = row_tag.find_all("th")

                if header_tags and not headers:
                    headers = [
                        header.get_text(" ", strip=True)
                        for header in header_tags
                    ]
                else:
                    rows.append(row_values)

            tables.append({
                "headers": headers,
                "rows": rows,
            })

        return tables

    def extract_lists(self, soup: BeautifulSoup) -> list[dict]:
        lists = []
        list_tags = soup.find_all(["ul", "ol"])

        for list_tag in list_tags:
            items = []
            li = list_tag.find_all("li")

            for li_tag in li:
                text = li_tag.get_text(" ", strip=True)
                items.append(text)

            lists.append({
                "type": list_tag.name,
                "items": items
            })

        return lists

class AsyncCrawler:
    def __init__(self, max_concurrent: int = 10):
        self.max_concurrency = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.session = None
        self.parser = HTMLParser()

    async def fetch_url(self, url: str) -> str | None:
        if self.session is None:

            timeout = aiohttp.ClientTimeout(connect=10, sock_read=2)
            self.session = aiohttp.ClientSession(timeout=timeout)

        logger.info("[DOWNLOAD] WAITING  | %s", url)

        async with self.semaphore:
            logger.info("[DOWNLOAD] STARTED  | %s", url)

            try:
                async with self.session.get(url) as response:
                    response.raise_for_status()
                    text = await response.text()
                    logger.info("[DOWNLOAD] FINISHED | %s", url)
                    return text
            except asyncio.TimeoutError:
                logger.warning("[DOWNLOAD] TIMEOUT  | %s", url)
            except aiohttp.ClientResponseError:
                logger.error("[DOWNLOAD] HTTP ERROR | %s", url)
            except aiohttp.ClientError:
                logger.error("[DOWNLOAD] NETWORK ERROR | %s", url)

            return None


    async def fetch_urls(self, urls: list[str]) -> dict[str, str | None]:
        result = await asyncio.gather(
            *(self.fetch_url(url) for url in urls)
        )

        return dict(zip(urls, result))

    async def fetch_and_parse(self, url: str) -> dict:
        html = await self.fetch_url(url)

        if html is None:
            logger.warning("Failed to fetch %s", url)

            return {
                "url": url,
                "title": "",
                "text": "",
                "links": [],
                "metadata": {},
            }

        result = await self.parser.parse_html(html, url)
        return result


    async def close(self) -> None:
        if self.session is not None and not self.session.closed:
            await self.session.close()
            self.session = None

async def main():
    crawler = AsyncCrawler(max_concurrent=4)
    urls = [
        "https://example.com",
        "https://www.python.org",
        "https://www.wikipedia.org",
        "https://httpbin.org/get",
        "https://httpbin.org/headers",
        "https://httpbin.org/uuid",
        "https://httpbin.org/status/404",
        "https://httpbin.org/status/500",
        "https://example.invalid",
        "https://httpbin.org/delay/10",
    ]

    started_at = time.perf_counter()

    try:
        results = await crawler.fetch_urls(urls)
        successful_count = 0

        for url, page_text in results.items():
            if page_text is None:
                logger.info("Failed: %s", url)
            else:
                successful_count += 1
                logger.info("Success: %s", url)

        async_time = time.perf_counter() - started_at

        logger.info("Processed URLs: %d", len(results))
        logger.info("Successfully downloaded pages: %d", successful_count)
        logger.info("Total time: %.2f seconds", async_time)

        parsed_started_at = time.perf_counter()

        parsed_results = await asyncio.gather(
            *(crawler.fetch_and_parse(url) for url in urls[:3])
        )

        parsed_time = time.perf_counter() - parsed_started_at

        logger.info("Parsed pages: %d", len(parsed_results))
        logger.info("Parsing time: %.2f seconds", parsed_time)

        for page in parsed_results:
            logger.info("Parsed URL: %s", page["url"])
            logger.info("Title: %s", page["title"])
            logger.info("Text length: %d",len(page.get("text", "")))
            logger.info("Links count: %d", len(page.get("links", [])))
            logger.info("Images count: %d",len(page.get("images", [])))
            logger.info("Headings count: %d",len(page.get("headings", [])))
            logger.info("Tables count: %d",len(page.get("tables", [])))
            logger.info("Lists count: %d",len(page.get("lists", [])))
    finally:
        await crawler.close()


if __name__ == "__main__":
    asyncio.run(main())


