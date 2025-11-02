import asyncio
import threading
import time
import aiohttp
from aiohttp_socks import ProxyConnector


class AsyncLoopThread:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()


_LOOP_THREAD = AsyncLoopThread()


class Proxy:
    def __init__(
        self,
        proxy_type="http",
        source="speedx",
        concurrency=50,
        test_url="http://httpbin.org/get",
        latency=False,
        custom_source=None,
    ):
        self.test_url = test_url
        self.proxy_type = proxy_type.lower()
        self.source = source.lower() if source else None
        self.concurrency = concurrency
        self.latency = latency
        self.custom_source = custom_source
        self._proxy_cache = None
        self.good_proxies = []

        self.sources = {
            "speedx": {
                "http": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
                "socks4": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
                "socks5": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
            },
            "monosans": {
                "http": "https://raw.githubusercontent.com/monosans/PROXY-List/master/proxies/http.txt",
                "socks4": "https://raw.githubusercontent.com/monosans/PROXY-List/master/proxies/socks4.txt",
                "socks5": "https://raw.githubusercontent.com/monosans/PROXY-List/master/proxies/socks5.txt",
            },
            "shiftytr": {
                "http": "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
                "socks4": "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks4.txt",
                "socks5": "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt",
            },
            "freeproxy": {
                "http": "https://raw.githubusercontent.com/FreeProxyList/FreeProxyList/main/http.txt",
                "socks4": "https://raw.githubusercontent.com/FreeProxyList/FreeProxyList/main/socks4.txt",
                "socks5": "https://raw.githubusercontent.com/FreeProxyList/FreeProxyList/main/socks5.txt",
            },
            "test": {
                "socks5": "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/protocols/socks5/data.txt",
            },
        }

        if self.custom_source:
            self.proxy_url = None
            print(f"Using custom proxy source: {self.custom_source}")
        else:
            try:
                self.proxy_url = self.sources[self.source][self.proxy_type]
                print(f"Using built-in source {self.source.upper()} ({self.proxy_type})")
            except KeyError:
                raise ValueError(
                    f"Unsupported combination or missing source: source='{self.source}', type='{self.proxy_type}'"
                )

    async def _get_list_async(self, force_refresh=False):
        if self._proxy_cache and not force_refresh:
            return self._proxy_cache

        proxy_list = []

        if self.custom_source:
            try:
                if isinstance(self.custom_source, list):
                    proxy_list = [p.strip() for p in self.custom_source if p.strip()]
                    print(f"Loaded {len(proxy_list)} proxies from custom list input.")
                elif isinstance(self.custom_source, str):
                    if self.custom_source.startswith(("http://", "https://")):
                        async with aiohttp.ClientSession() as session:
                            async with session.get(self.custom_source, timeout=10) as resp:
                                text = await resp.text()
                    else:
                        with open(self.custom_source, "r") as f:
                            text = f.read()
                    proxy_list = [p.strip() for p in text.splitlines() if p.strip()]
                    print(f"Loaded {len(proxy_list)} proxies from custom source.")
                else:
                    print("Unsupported custom source format. Expected list, URL, or file path.")
            except Exception as e:
                print(f"Failed to load custom proxy list: {e}")
        elif self.proxy_url:
            print(f"Fetching proxies from {self.proxy_url} ...")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.proxy_url, timeout=10) as resp:
                        text = await resp.text()
                proxy_list = [p.strip() for p in text.splitlines() if p.strip()]
                print(f"Loaded {len(proxy_list)} proxies from {self.source}")
            except Exception as e:
                print(f"Failed to fetch proxy list: {e}")

        clean_list = []
        for item in proxy_list:
            if "://" in item:
                item = item.split("://", 1)[1]
            clean_list.append(item)

        self._proxy_cache = clean_list
        return clean_list

    async def _is_live_async(self, proxy_ip_port, test_url, timeout=3, latency=False):
        proxy_url = f"{self.proxy_type}://{proxy_ip_port}"
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        start = time.perf_counter()

        try:
            if self.proxy_type in ("socks4", "socks5"):
                connector = ProxyConnector.from_url(proxy_url)
                async with aiohttp.ClientSession(connector=connector, timeout=timeout_obj) as session:
                    async with session.get(test_url) as resp:
                        if resp.status == 200:
                            end = time.perf_counter()
                            return (True, end - start) if latency else True
            else:
                async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                    async with session.get(test_url, proxy=proxy_url) as resp:
                        if resp.status == 200:
                            end = time.perf_counter()
                            return (True, end - start) if latency else True
        except Exception:
            pass

        return (False, None) if latency else False

    async def _find_first_live_proxy_async(self):
        proxy_list = await self._get_list_async()
        if not proxy_list:
            return None

        semaphore = asyncio.Semaphore(self.concurrency)

        async def test_proxy(proxy):
            async with semaphore:
                print(f"Testing proxy: {proxy}")
                if await self._is_live_async(proxy, self.test_url):
                    print(f"Live proxy found: {proxy}")
                    return proxy
                print(f"Dead proxy: {proxy}")
                return None

        tasks = [test_proxy(p) for p in proxy_list]
        for fut in asyncio.as_completed(tasks):
            result = await fut
            if result:
                return result

        print("No live proxy found.")
        return None

    async def _find_all_live_proxies_async(self):
        proxy_list = await self._get_list_async()
        if not proxy_list:
            return []

        semaphore = asyncio.Semaphore(self.concurrency)
        live = []

        async def test_proxy(proxy):
            async with semaphore:
                print(f"Testing proxy: {proxy}")
                result = await self._is_live_async(proxy, self.test_url, latency=self.latency)
                if self.latency:
                    is_live, delay = result
                    if is_live:
                        print(f"Live proxy: {proxy} ({delay*1000:.1f} ms)")
                        live.append({"proxy": proxy, "latency": delay})
                    else:
                        print(f"Dead proxy: {proxy}")
                else:
                    if result:
                        print(f"Live proxy: {proxy}")
                        live.append(proxy)
                    else:
                        print(f"Dead proxy: {proxy}")

        tasks = [test_proxy(p) for p in proxy_list]
        for fut in asyncio.as_completed(tasks):
            await fut

        if self.latency:
            live.sort(key=lambda x: x["latency"])

        self.good_proxies = live
        print(f"Found {len(live)} live proxies.")
        return live

    def get_random_proxy(self):
        if self.latency:
            results = _LOOP_THREAD.run(self._find_all_live_proxies_async())
            if results:
                fastest = results[0]["proxy"]
                print(f"Fastest proxy selected: {fastest} ({results[0]['latency']*1000:.1f} ms)")
                return fastest
            else:
                print("No live proxies found.")
                return None
        else:
            return _LOOP_THREAD.run(self._find_first_live_proxy_async())

    def get_good_proxies(self):
        return _LOOP_THREAD.run(self._find_all_live_proxies_async())

