import streamlit as st
import requests
import re
import time
import random
from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import pandas as pd
from datetime import datetime

# Configurare pagină
st.set_page_config(
    page_title="Analizor Preț OLX",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Headers pentru requests
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

@dataclass
class CarSpecs:
    title: str
    price: float
    price_text: str
    brand: str
    model: str
    year: int
    km: int
    fuel: str
    gearbox: str
    body: str
    power: Optional[int]
    engine_size: Optional[int]
    state: str
    color: str
    link: str

class OLXExtractorFixed:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._current_url: Optional[str] = None

    # -------- utils --------

    def normalize_numeric_text(self, text: str) -> str:
        """Normalizează textul numeric (spații NBSP/înguste -> space)."""
        if not text:
            return ""
        text = re.sub(r"[\u00A0\u202F]+", " ", text)   # NBSP / thin space
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def extract_number_from_text(self, text: str) -> Optional[int]:
        """Extrage un int din text (elim. puncte/virgule/spații)."""
        if not text:
            return None
        text = self.normalize_numeric_text(text)
        m = re.search(r"(\d[\d\s\.,]*)", text)
        if not m:
            return None
        clean = re.sub(r"[^\d]", "", m.group(1))
        try:
            return int(clean)
        except Exception:
            return None

    # -------- title --------

    def extract_title(self, soup: BeautifulSoup) -> str:
        # 1) og:title
        tag = soup.find("meta", {"property": "og:title"})
        if tag and tag.get("content"):
            content = tag["content"].strip()
            if not re.search(r"anun[tț]uri gratuite|olx\.ro", content, re.I):
                return content

        # 2) <title>
        if soup.title and soup.title.get_text(strip=True):
            title_text = soup.title.get_text(strip=True)
            # curăță sufixele gen " | OLX.ro" sau " - OLX.ro"
            title_text = re.sub(r"\s*\|\s*OLX\.ro.*$", "", title_text, flags=re.I)
            title_text = re.sub(r"\s*-\s*OLX\.ro.*$", "", title_text, flags=re.I)
            if not re.search(r"anun[tț]uri gratuite|olx\.ro", title_text, re.I) and len(title_text) > 10:
                return title_text

        # 3) primul H1 rezonabil
        for h1 in soup.find_all("h1"):
            t = h1.get_text(strip=True)
            if t and len(t) > 10 and not re.search(r"anun[tț]uri|olx", t, re.I):
                return t

        # 4) JSON-LD name/headline
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict):
                    cand = data.get("name") or data.get("headline")
                    if cand and len(cand) > 10 and not re.search(r"olx|anun[tț]uri", cand, re.I):
                        return cand.strip()
            except Exception:
                pass

        # 5) fallback din canonical
        link = soup.find("link", {"rel": "canonical", "href": True})
        href = link["href"] if link else (self._current_url or "")
        m = re.search(r"/d/oferta/([^/]+)", href)
        if m:
            url_part = m.group(1)
            url_part = re.sub(r"-ID.*$", "", url_part)
            return url_part.replace("-", " ").title()

        return "Titlu necunoscut"

    # -------- price --------

    def extract_price(self, soup: BeautifulSoup) -> Tuple[float, str]:
        """Extrage prețul (meta → text vizibil)."""
        # 1) meta
        meta_price = soup.find("meta", {"property": "product:price:amount"})
        meta_currency = soup.find("meta", {"property": "product:price:currency"})
        if meta_price and meta_price.get("content"):
            try:
                val = float(meta_price["content"])
                cur = (meta_currency["content"] if meta_currency and meta_currency.get("content") else "EUR").upper()
                return val, f"{int(val):,} {cur}".replace(",", " ")
            except Exception:
                pass

        # 2) text vizibil (exclude script/style)
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        visible = soup.get_text(" ", strip=True)
        pattern = r"(\d[\d\s\u00A0\u202F\.,]*)\s*(€|eur|euro|lei|ron)\b"
        for m in re.finditer(pattern, visible, re.I):
            price_str = self.normalize_numeric_text(m.group(1))
            currency = m.group(2).lower()
            num = self.extract_number_from_text(price_str)
            if num and num > 100:  # filtru anti-zgomot
                cur = "EUR" if currency in ("€", "eur", "euro") else "LEI"
                return float(num), f"{num:,} {cur}".replace(",", " ")
        return 0.0, "0 EUR"

    # -------- brand/model fallbacks --------

    def extract_brand_from_breadcrumb(self, soup: BeautifulSoup) -> Optional[str]:
        brands = {
            "ford","bmw","mercedes","audi","volkswagen","volvo","toyota","honda","nissan",
            "renault","peugeot","opel","dacia","hyundai","kia","mazda","skoda","citroen",
            "subaru","mitsubishi","suzuki","lexus","porsche","jaguar","land rover","range rover"
        }
        # caută text în <a>/<span>/<li>
        for el in soup.find_all(["a", "span", "li"]):
            t = (el.get_text(strip=True) or "").lower()
            if t in brands:
                return t.title()
        # caută în href
        for a in soup.find_all("a", href=True):
            h = a["href"].lower()
            for b in brands:
                if f"/{b.replace(' ', '-')}/" in h or f"{b.replace(' ', '-')}-" in h:
                    return b.title()
        return None

    def extract_brand_and_model_from_url(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        if not url:
            return None, None
        m = re.search(r"/d/oferta/([^/]+)", url)
        if not m:
            return None, None
        url_part = m.group(1).lower()

        brand_list = [
            "ford","bmw","mercedes","audi","volkswagen","volvo","toyota","honda","nissan",
            "renault","peugeot","opel","dacia","hyundai","kia","mazda","skoda","citroen",
            "subaru","mitsubishi","suzuki","lexus","infiniti","porsche","jaguar",
            "land-rover","range-rover"
        ]
        brand_found = None
        model_found = None
        for brand in brand_list:
            if url_part.startswith(brand + "-"):
                brand_found = brand.replace("-", " ").title()
                remaining = url_part[len(brand) + 1 :]
                # primul token care NU e an (4 cifre) îl luăm drept model
                parts = remaining.split("-")
                if parts:
                    candidate = parts[0]
                    if not re.match(r"^\d{4}$", candidate):
                        model_found = candidate.upper()
                break
        return brand_found, model_found

    # -------- specs --------

    def extract_specs_from_structured_data(self, soup: BeautifulSoup) -> Dict:
        specs: Dict[str, object] = {}

        # 1) JSON-LD (nu folosim pentru model; doar ca fallback pe viitor)
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict) and data.get("@type") == "Vehicle":
                    pass
            except Exception:
                pass

        # 2) Regex pe text vizibil
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = self.normalize_numeric_text(soup.get_text(" ", strip=True))

        patterns = {
            "year": r"(?:an(?:ul)?|fabricat|fabricație|fabricatie)\D{0,12}(\d{4})",
            "km": r"(\d[\d\s\u00A0\u202F\.,]*)\s*km\b",
            "engine_size": r"(\d[\d\s\u00A0\u202F\.,]*)\s*(?:cm3|cmc|cm³)\b",
            "power": r"(\d[\d\s\u00A0\u202F\.,]*)\s*(?:cp|hp|cai)\b",
            "fuel": r"(?:combustibil|fuel)\D{0,12}(diesel|benzină|benzina|petrol|gpl|hibrid|electric|hybrid)",
            "gearbox": r"(?:cutie|transmis(?:ie)?|gearbox)\D{0,12}(automată|automata|manuală|manuala|automatic|manual)",
            "body": r"(?:caroserie|tip|body)\D{0,12}(suv|sedan|berlină|berlina|break|coupe|hatchback|pickup|pick-up)",
            "state": r"(?:stare|condition)\D{0,12}(nou|new|folosit|utilizat|used)",
        }

        for key, pat in patterns.items():
            m = re.search(pat, text, re.I)
            if not m:
                continue
            val = m.group(1)
            if key in {"year", "km", "engine_size", "power"}:
                n = self.extract_number_from_text(val)
                if n is None:
                    continue
                if key == "year" and 1990 <= n <= 2025:
                    specs["year"] = n
                elif key == "km" and 0 <= n <= 1_500_000:
                    specs["km"] = n
                elif key == "engine_size" and 500 <= n <= 8000:
                    specs["engine_size"] = n
                elif key == "power" and 30 <= n <= 2000:
                    specs["power"] = n
            else:
                v = val.lower().strip()
                if key == "fuel":
                    specs["fuel"] = {
                        "diesel": "diesel",
                        "benzină": "petrol", "benzina": "petrol", "petrol": "petrol",
                        "gpl": "lpg",
                        "hibrid": "hybrid", "hybrid": "hybrid",
                        "electric": "electric",
                    }.get(v, v)
                elif key == "gearbox":
                    specs["gearbox"] = {
                        "automată": "automatic", "automata": "automatic", "automatic": "automatic",
                        "manuală": "manual", "manuala": "manual", "manual": "manual",
                    }.get(v, v)
                elif key == "body":
                    specs["body"] = {
                        "suv": "suv", "sedan": "sedan", "berlină": "sedan", "berlina": "sedan",
                        "break": "estate-car", "coupe": "coupe", "hatchback": "hatchback",
                        "pickup": "pickup", "pick-up": "pickup",
                    }.get(v, v)
                elif key == "state":
                    specs["state"] = {
                        "nou": "new", "new": "new",
                        "folosit": "used", "utilizat": "used", "used": "used",
                    }.get(v, "used")

        # 3) brand din breadcrumb
        b = self.extract_brand_from_breadcrumb(soup)
        if b:
            specs["brand"] = b

        # 4) fallback brand/model din URL (canonical sau _current_url)
        link = soup.find("link", {"rel": "canonical", "href": True})
        href = link["href"] if link else (self._current_url or "")
        brand_u, model_u = self.extract_brand_and_model_from_url(href)
        if brand_u and "brand" not in specs:
            specs["brand"] = brand_u
        if model_u and "model" not in specs:
            specs["model"] = model_u

        return specs

    # -------- main entry --------

    def extract_car_specs(self, url: str) -> Optional[CarSpecs]:
        """Extragere completă cu fixuri."""
        try:
            self._current_url = url
            time.sleep(random.uniform(1.2, 2.2))  # throttling light
            resp = self.session.get(url, timeout=20)
            if resp.status_code != 200:
                print(f"Eroare HTTP: {resp.status_code}")
                return None
            soup = BeautifulSoup(resp.content, "html.parser")

            title = self.extract_title(soup)
            price_num, price_txt = self.extract_price(soup)
            specs = self.extract_specs_from_structured_data(soup)

            return CarSpecs(
                title=title or "Titlu necunoscut",
                price=price_num or 0.0,
                price_text=price_txt or "0 EUR",
                brand=specs.get("brand", "Unknown"),
                model=specs.get("model", "Unknown"),
                year=int(specs.get("year", 0) or 0),
                km=int(specs.get("km", 0) or 0),
                fuel=str(specs.get("fuel", "Unknown")),
                gearbox=str(specs.get("gearbox", "Unknown")),
                body=str(specs.get("body", "Unknown")),
                power=specs.get("power"),
                engine_size=specs.get("engine_size"),
                state=str(specs.get("state", "Unknown")),
                link=url,
            )
        except Exception as e:
            print(f"Eroare la extragerea datelor: {e}")
            return None

# ---- Test rapid ----
def test_extractor():
    extractor = OLXExtractorFixed()
    test_url = "https://www.olx.ro/d/oferta/ford-ranger-wildtrack-2021-2l-a10-full-105000km-tva-deductibil-IDjFQ7O.html"
    print("=== TEST EXTRACTOR CORECTAT ===")
    result = extractor.extract_car_specs(test_url)
    if result:
        print(f"Titlu: {result.title}")
        print(f"Preț: {result.price_text} (numeric: {result.price})")
        print(f"Marca: {result.brand}")
        print(f"Model: {result.model}")
        print(f"An: {result.year}")
        print(f"KM: {result.km:,}")
        print(f"Combustibil: {result.fuel}")
        print(f"Cutie: {result.gearbox}")
        print(f"Caroserie: {result.body}")
        print(f"Putere: {result.power} CP")
        print(f"Capacitate: {result.engine_size} cm³")
        print(f"Stare: {result.state}")
    else:
        print("Nu s-au putut extrage datele")

if __name__ == "__main__":
    test_extractor()


class URLBuilder:
    """Construiește URL-uri pentru căutări OLX"""
    
    BRAND_SLUGS = {
        'Audi': 'audi', 'BMW': 'bmw', 'Mercedes': 'mercedes-benz',
        'Volkswagen': 'volkswagen', 'Skoda': 'skoda', 'Ford': 'ford',
        'Volvo': 'volvo', 'Toyota': 'toyota', 'Honda': 'honda',
        'Nissan': 'nissan', 'Opel': 'opel', 'Peugeot': 'peugeot'
    }
    
    @classmethod
    def build_search_url(cls, car: CarSpecs, tolerances: Dict) -> str:
        """Construiește URL-ul de căutare pe baza specificațiilor și toleranțelor"""
        
        brand_slug = cls.BRAND_SLUGS.get(car.brand, car.brand.lower())
        base_url = f"https://www.olx.ro/auto-masini-moto-ambarcatiuni/autoturisme/{brand_slug}/"
        
        params = []
        params.append("currency=EUR")
        params.append("search%5Bprivate_business%5D=private")
        
        # Model
        if car.model != 'Unknown':
            model_slug = car.model.lower().replace(' ', '-')
            params.append(f"search%5Bfilter_enum_model%5D%5B0%5D={model_slug}")
        
        # An
        if car.year > 0:
            year_min = max(2000, car.year - tolerances['years'])
            year_max = min(2025, car.year + tolerances['years'])
            params.append(f"search%5Bfilter_float_year%3Afrom%5D={year_min}")
            params.append(f"search%5Bfilter_float_year%3Ato%5D={year_max}")
        
        # Kilometri
        if car.km > 0:
            km_min = max(0, car.km - tolerances['km'])
            km_max = car.km + tolerances['km']
            params.append(f"search%5Bfilter_float_rulaj_pana%3Afrom%5D={km_min}")
            params.append(f"search%5Bfilter_float_rulaj_pana%3Ato%5D={km_max}")
        
        # Putere
        if car.power and tolerances.get('power'):
            power_min = max(50, car.power - tolerances['power'])
            power_max = car.power + tolerances['power']
            params.append(f"search%5Bfilter_float_engine_power%3Afrom%5D={power_min}")
            params.append(f"search%5Bfilter_float_engine_power%3Ato%5D={power_max}")
        
        # Capacitate motor
        if tolerances.get('engine_min') and tolerances.get('engine_max'):
            params.append(f"search%5Bfilter_float_enginesize%3Afrom%5D={tolerances['engine_min']}")
            params.append(f"search%5Bfilter_float_enginesize%3Ato%5D={tolerances['engine_max']}")
        
        # Combustibil
        if tolerances.get('fuel_types'):
            for i, fuel in enumerate(tolerances['fuel_types']):
                params.append(f"search%5Bfilter_enum_petrol%5D%5B{i}%5D={fuel}")
        
        # Caroserie
        if car.body != 'Unknown':
            params.append(f"search%5Bfilter_enum_car_body%5D%5B0%5D={car.body}")
        
        # Cutie
        if tolerances.get('gearbox_types'):
            for i, gearbox in enumerate(tolerances['gearbox_types']):
                params.append(f"search%5Bfilter_enum_gearbox%5D%5B{i}%5D={gearbox}")
        
        # Stare
        if tolerances.get('state_types'):
            for i, state in enumerate(tolerances['state_types']):
                params.append(f"search%5Bfilter_enum_state%5D%5B{i}%5D={state}")
        
        return f"{base_url}?{'&'.join(params)}"

class PriceAnalyzer:
    """Analizează și clasifică anunțurile"""
    
    @classmethod
    def classify_car(cls, reference_car: CarSpecs, comparison_car: CarSpecs) -> Tuple[str, int, str]:
        """Clasifică un anunț față de referință"""
        score = 100
        explanation_parts = []
        
        # Verifică criteriile obligatorii (Nivel 1)
        if comparison_car.brand != reference_car.brand or comparison_car.model != reference_car.model:
            return "EXCLUS", 0, "Marcă sau model diferit"
        
        # Analizează prețul
        price_diff = comparison_car.price - reference_car.price
        price_diff_percent = (price_diff / reference_car.price) * 100 if reference_car.price > 0 else 0
        
        if price_diff < 0:
            explanation_parts.append(f"Mai ieftin cu {abs(price_diff):.0f} EUR")
            score += min(20, abs(price_diff_percent))
        else:
            explanation_parts.append(f"Mai scump cu {price_diff:.0f} EUR")
            score -= min(30, price_diff_percent)
        
        # Analizează anii
        year_diff = comparison_car.year - reference_car.year
        if year_diff > 0:
            explanation_parts.append(f"Mai nou cu {year_diff} an(i)")
            score += year_diff * 5
        elif year_diff < 0:
            explanation_parts.append(f"Mai vechi cu {abs(year_diff)} an(i)")
            score -= abs(year_diff) * 5
        
        # Analizează kilometrii
        km_diff = comparison_car.km - reference_car.km
        if km_diff < 0:
            explanation_parts.append(f"Mai puțini km cu {abs(km_diff):,}")
            score += min(15, abs(km_diff) / 10000)
        elif km_diff > 0:
            explanation_parts.append(f"Mai mulți km cu {km_diff:,}")
            score -= min(20, km_diff / 10000)
        
        # Analizează combustibilul
        if comparison_car.fuel != reference_car.fuel:
            explanation_parts.append(f"Combustibil diferit: {comparison_car.fuel} vs {reference_car.fuel}")
            score -= 15
        
        # Clasificare finală
        if score >= 90:
            category = "EXCELENT"
        elif score >= 70:
            category = "BUN"
        elif score >= 50:
            category = "ACCEPTABIL"
        else:
            category = "SLAB"
        
        explanation = " • ".join(explanation_parts) if explanation_parts else "Specificații similare"
        
        return category, int(score), explanation

# UI Principal
def main():
    st.title("🚗 Analizor Preț OLX")
    st.markdown("Analizează dacă un anunț auto are preț bun comparativ cu piața")
    
    # Sidebar pentru configurări
    st.sidebar.header("⚙️ Configurări")
    
    # Input URL
    url = st.text_input("🔗 Link anunț OLX:", placeholder="https://www.olx.ro/d/oferta/...")
    
    if not url:
        st.info("Introduceți link-ul unui anunț OLX pentru a începe analiza")
        return
    
    # Validare URL
    if not re.match(r'https?://.*olx\.ro.*', url):
        st.error("Link-ul nu pare să fie de pe OLX România")
        return
    
    # Configurări toleranțe
    st.sidebar.subheader("📊 Toleranțe")
    years_tolerance = st.sidebar.slider("Ani (±)", 1, 5, 2)
    km_tolerance = st.sidebar.slider("Kilometri (±)", 10000, 100000, 30000, step=5000)
    power_tolerance = st.sidebar.slider("Putere CP (±)", 0, 50, 20, step=5)
    
    # Capacitate motor
    st.sidebar.subheader("⚡ Capacitate motor")
    engine_min = st.sidebar.number_input("Minim (cm³)", 800, 5000, 1500, step=100)
    engine_max = st.sidebar.number_input("Maxim (cm³)", 800, 5000, 2500, step=100)
    
    # Filtre suplimentare
    st.sidebar.subheader("🔧 Filtre")
    fuel_options = ['diesel', 'petrol', 'lpg', 'hybrid', 'electric']
    selected_fuels = st.sidebar.multiselect("Combustibil acceptat:", fuel_options, default=['diesel'])
    
    gearbox_options = ['manual', 'automatic']
    selected_gearbox = st.sidebar.multiselect("Cutie viteze:", gearbox_options, default=['automatic'])
    
    state_options = ['used', 'new']
    selected_states = st.sidebar.multiselect("Stare:", state_options, default=['used'])
    
    if st.button("🔍 Analizează Prețul", type="primary"):
        with st.spinner("Extrag datele din anunț..."):
            extractor = OLXExtractorFixed()
            car_specs = extractor.extract_car_specs(url)
            
            if not car_specs:
                st.error("Nu am putut extrage datele din anunț")
                return
            
            # Afișează datele extrase
            st.success("Datele au fost extrase cu succes!")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("📋 Specificații Anunț")
                st.write(f"**Titlu:** {car_specs.title}")
                st.write(f"**Preț:** {car_specs.price_text}")
                st.write(f"**Marcă:** {car_specs.brand}")
                st.write(f"**Model:** {car_specs.model}")
                st.write(f"**An:** {car_specs.year}")
                st.write(f"**Kilometri:** {car_specs.km:,}")
            
            with col2:
                st.subheader("🔧 Specificații Tehnice")
                st.write(f"**Combustibil:** {car_specs.fuel}")
                st.write(f"**Cutie:** {car_specs.gearbox}")
                st.write(f"**Caroserie:** {car_specs.body}")
                if car_specs.power:
                    st.write(f"**Putere:** {car_specs.power} CP")
                if car_specs.engine_size:
                    st.write(f"**Capacitate:** {car_specs.engine_size} cm³")
                st.write(f"**Stare:** {car_specs.state}")
            
            # Construiește căutarea
            tolerances = {
                'years': years_tolerance,
                'km': km_tolerance,
                'power': power_tolerance,
                'engine_min': engine_min,
                'engine_max': engine_max,
                'fuel_types': selected_fuels,
                'gearbox_types': selected_gearbox,
                'state_types': selected_states
            }
            
            search_url = URLBuilder.build_search_url(car_specs, tolerances)
            st.write(f"**URL căutare:** {search_url}")
            
            # Simulare rezultate (pentru test)
            st.subheader("📊 Rezultate Analiză")
            st.info("Funcționalitatea de căutare anunțuri similare va fi implementată în următorul pas")

if __name__ == "__main__":
    main()
