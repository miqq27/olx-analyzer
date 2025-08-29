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

class OLXExtractor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
    
    def extract_car_specs(self, url: str) -> Optional[CarSpecs]:
        """Extrage specificațiile din anunțul OLX"""
        try:
            time.sleep(random.uniform(2, 4))  # Anti-blocare
            response = self.session.get(url, timeout=15)
            
            if response.status_code != 200:
                st.error(f"Nu pot accesa anunțul. Status code: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extrage titlul
            title_elem = soup.find('h1', {'data-cy': 'ad_title'}) or soup.find('h1')
            title = title_elem.get_text(strip=True) if title_elem else "Titlu necunoscut"
            
            # Extrage prețul
            price_elem = soup.find('h3', {'data-testid': 'ad-price-container'}) or soup.find('h3', class_=re.compile('price'))
            price_text = "0 EUR"
            price_numeric = 0
            
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                # Extrage numărul din preț
                price_match = re.search(r'([\d\s.,]+)', price_text.replace('€', '').replace('EUR', '').replace('lei', ''))
                if price_match:
                    price_clean = price_match.group(1).replace('.', '').replace(',', '').replace(' ', '')
                    try:
                        price_numeric = float(price_clean)
                    except:
                        pass
            
            # Extrage specificațiile din tabel
            specs = self._extract_specs_from_table(soup)
            
            return CarSpecs(
                title=title,
                price=price_numeric,
                price_text=price_text,
                brand=specs.get('brand', 'Unknown'),
                model=specs.get('model', 'Unknown'),
                year=specs.get('year', 0),
                km=specs.get('km', 0),
                fuel=specs.get('fuel', 'Unknown'),
                gearbox=specs.get('gearbox', 'Unknown'),
                body=specs.get('body', 'Unknown'),
                power=specs.get('power'),
                engine_size=specs.get('engine_size'),
                state=specs.get('state', 'Unknown'),
                color=specs.get('color', 'Unknown'),
                link=url
            )
            
        except Exception as e:
            st.error(f"Eroare la extragerea datelor: {str(e)}")
            return None
    
    def _extract_specs_from_table(self, soup) -> Dict:
        """Extrage specificațiile din tabelul de date"""
        specs = {}
        
        # Caută toate textele care conțin specificații
        text_elements = soup.find_all(string=re.compile(r'(An de fabricatie|Rulaj|Combustibil|Cutie|Caroserie|Marca|Model)', re.I))
        
        for elem in text_elements:
            parent = elem.parent
            if parent:
                full_text = parent.get_text(strip=True)
                
                # An de fabricație
                if re.search(r'an de fabricatie', full_text, re.I):
                    year_match = re.search(r'(\d{4})', full_text)
                    if year_match:
                        specs['year'] = int(year_match.group(1))
                
                # Kilometri
                elif re.search(r'rulaj', full_text, re.I):
                    km_match = re.search(r'([\d\s.,]+)', full_text.replace('km', ''))
                    if km_match:
                        km_clean = km_match.group(1).replace('.', '').replace(',', '').replace(' ', '')
                        try:
                            specs['km'] = int(km_clean)
                        except:
                            pass
                
                # Combustibil
                elif re.search(r'combustibil', full_text, re.I):
                    if 'diesel' in full_text.lower():
                        specs['fuel'] = 'diesel'
                    elif 'benzina' in full_text.lower() or 'petrol' in full_text.lower():
                        specs['fuel'] = 'petrol'
                    elif 'gpl' in full_text.lower():
                        specs['fuel'] = 'lpg'
                    elif 'hibrid' in full_text.lower():
                        specs['fuel'] = 'hybrid'
                    elif 'electric' in full_text.lower():
                        specs['fuel'] = 'electric'
                
                # Cutie de viteze
                elif re.search(r'cutie', full_text, re.I):
                    if 'automata' in full_text.lower():
                        specs['gearbox'] = 'automatic'
                    elif 'manuala' in full_text.lower():
                        specs['gearbox'] = 'manual'
                
                # Caroserie
                elif re.search(r'caroserie', full_text, re.I):
                    if 'suv' in full_text.lower():
                        specs['body'] = 'suv'
                    elif 'sedan' in full_text.lower() or 'berlina' in full_text.lower():
                        specs['body'] = 'sedan'
                    elif 'break' in full_text.lower():
                        specs['body'] = 'estate-car'
                    elif 'coupe' in full_text.lower():
                        specs['body'] = 'coupe'
                    elif 'hatchback' in full_text.lower():
                        specs['body'] = 'hatchback'
                
                # Putere (CP)
                elif re.search(r'(putere|cp|cai)', full_text, re.I):
                    power_match = re.search(r'(\d+)', full_text)
                    if power_match:
                        specs['power'] = int(power_match.group(1))
                
                # Capacitate motor
                elif re.search(r'(capacitate|cm|litri)', full_text, re.I):
                    capacity_match = re.search(r'(\d+)', full_text)
                    if capacity_match:
                        specs['engine_size'] = int(capacity_match.group(1))
        
        # Încearcă să extragi marca și modelul din titlu ca fallback
        if 'brand' not in specs or 'model' not in specs:
            title = soup.find('h1')
            if title:
                title_text = title.get_text(strip=True).lower()
                brands = ['audi', 'bmw', 'mercedes', 'volkswagen', 'skoda', 'ford', 'volvo', 'toyota', 'honda', 'nissan']
                for brand in brands:
                    if brand in title_text:
                        specs['brand'] = brand.title()
                        # Încearcă să extragi modelul
                        words = title_text.split()
                        try:
                            brand_idx = words.index(brand)
                            if brand_idx + 1 < len(words):
                                specs['model'] = words[brand_idx + 1].upper()
                        except:
                            pass
                        break
        
        return specs

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
            extractor = OLXExtractor()
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
