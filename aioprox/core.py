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
        debug=False,
    ):
        self.test_url = test_url
        self.proxy_type = proxy_type.lower()
        self.source = source.lower() if source else None
        self.concurrency = concurrency
        self.latency = latency
        self.custom_source = custom_source
        self.debug = debug
        self._proxy_cache = None
        self.good_proxies = []

        # Built-in proxy sources
        self.sources = {
            "speedx": {
                "http": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/refs/heads/master/http.txt",
                "socks4": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
                "socks5": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
            },
            "proxifly": { #new source added
                "http": "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/protocols/http/data.txt",
                "socks4": "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/protocols/socks4/data.txt",
                "socks5": "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/protocols/socks5/data.txt",},

            "databay": { #new source added

                "http": "https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/http.txt",
                "socks5": "https://raw.githubusercontent.com/databay-labs/free-proxy-list/refs/heads/master/socks5.txt",},
        }

        if self.custom_source:
            self.proxy_url = None
            if self.debug:
                print(f"[INFO] Using custom proxy source: {self.custom_source}")
        else:
            try:
                self.proxy_url = self.sources[self.source][self.proxy_type]
                if self.debug:
                    print(f"[INFO] Using built-in source {self.source.upper()} ({self.proxy_type})")
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
                    if self.debug:
                        print(f"[INFO] Loaded {len(proxy_list)} proxies from custom list input.")
                elif isinstance(self.custom_source, str):
                    if self.custom_source.startswith(("http://", "https://")):
                        async with aiohttp.ClientSession() as session:
                            async with session.get(self.custom_source, timeout=10) as resp:
                                text = await resp.text()
                    else:
                        with open(self.custom_source, "r") as f:
                            text = f.read()
                    proxy_list = [p.strip() for p in text.splitlines() if p.strip()]
                    if self.debug:
                        print(f"[INFO] Loaded {len(proxy_list)} proxies from custom source.")
                else:
                    if self.debug:
                        print("[WARNING] Unsupported custom source format. Expected list, URL, or file path.")
            except Exception as e:
                if self.debug:
                    print(f"[ERROR] Failed to load custom proxy list: {e}")
        elif self.proxy_url:
            if self.debug:
                print(f"[INFO] Fetching proxies from {self.proxy_url} ...")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.proxy_url, timeout=10) as resp:
                        text = await resp.text()
                proxy_list = [p.strip() for p in text.splitlines() if p.strip()]
                if self.debug:
                    print(f"[INFO] Loaded {len(proxy_list)} proxies from {self.source}")
            except Exception as e:
                if self.debug:
                    print(f"[ERROR] Failed to fetch proxy list: {e}")

        # Clean entries
        clean_list = [p.split("://", 1)[1] if "://" in p else p for p in proxy_list]
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

    async def _find_first_live_proxy_async(self, test_url=None):
        proxy_list = await self._get_list_async()
        if not proxy_list:
            return None

        semaphore = asyncio.Semaphore(self.concurrency)
        test_url = test_url or self.test_url

        async def test_proxy(proxy):
            async with semaphore:
                result = await self._is_live_async(proxy, test_url, latency=self.latency)
                if self.latency:
                    is_live, _ = result
                    return proxy if is_live else None
                else:
                    return proxy if result else None

        tasks = [test_proxy(p) for p in proxy_list]
        for fut in asyncio.as_completed(tasks):
            result = await fut
            if result:
                return result
        return None

    async def _find_all_live_proxies_async(self):
        proxy_list = await self._get_list_async()
        if not proxy_list:
            return []

        semaphore = asyncio.Semaphore(self.concurrency)
        live = []

        async def test_proxy(proxy):
            async with semaphore:
                result = await self._is_live_async(proxy, self.test_url, latency=self.latency)
                if self.latency:
                    is_live, delay = result
                    if is_live:
                        live.append({"proxy": proxy, "latency": delay})
                else:
                    if result:
                        live.append(proxy)

        tasks = [test_proxy(p) for p in proxy_list]
        for fut in asyncio.as_completed(tasks):
            await fut

        if self.latency:
            live.sort(key=lambda x: x["latency"])

        self.good_proxies = live
        return live

    def get_random_proxy(self, test_url=None):
        """Return a single live proxy. Can specify a custom test_url."""
        if self.latency:
            results = _LOOP_THREAD.run(self._find_all_live_proxies_async())
            if results:
                return results[0]["proxy"]
            return None
        return _LOOP_THREAD.run(self._find_first_live_proxy_async(test_url=test_url))

    def get_good_proxies(self):
        return _LOOP_THREAD.run(self._find_all_live_proxies_async())
