import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

from storage import SpatialDataStore

app = FastAPI(title="Flood Risk Analysis Application")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create necessary directories
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(exist_ok=True)

client = OpenAI(api_key="sk-svcacct-8Y_mxVNnuZW8S6GIGVsoHpqNcqONmgUyxxVxY00u5y4ZD42MVRr8SYUFW0L0dePw_n-nVT3BlbkFJ9kQPd-v1NbAr3MQl58elUVR-_woB3tMX_6DjGbfk09NQJULKKZBytuXnWiO6eSbbVk-AA")

# Constants
WEATHER_CONFIG = {
    "api_key": "4e203ee12a8247af85f122549240612",
    "forecast_days": 7,
    "update_interval": 3600000  # 1 hour
}

OPENAI_CONFIG = {
    "api_key": 'sk-svcacct-8Y_mxVNnuZW8S6GIGVsoHpqNcqONmgUyxxVxY00u5y4ZD42MVRr8SYUFW0L0dePw_n-nVT3BlbkFJ9kQPd-v1NbAr3MQl58elUVR-_woB3tMX_6DjGbfk09NQJULKKZBytuXnWiO6eSbbVk-AA',
    "model": "gpt-3",
    "endpoint": "https://api.openai.com/v1/chat/completions",
}

FLOOD_RISK_CONFIG = {
    "elevation_threshold": 5,  # meters above nearest waterway
    "rainfall_threshold": 50,  # mm per day
    "soil_saturation_threshold": 0.8,  # 0-1 scale
    "water_level_threshold": 2  # meters above normal
}

ANALYSIS_RADIUS = 2500  # 2km radius for analysis


class Point(BaseModel):
    lat: float
    lng: float


class AnalysisRequest(BaseModel):
    point: Point
    radius: float = ANALYSIS_RADIUS


def init_static_files():
    """Initialize static files for the web interface"""
    html_content = """
    <!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shapefile Loader</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
     <script src="https://cdn.jsdelivr.net/particles.js/2.0.0/particles.min.js"></script>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script src="https://d3js.org/topojson.v3.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background-color: #fff;
            color: #333;
            font-family: 'Arial', sans-serif;
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
            position: relative;
        }

        #map {
            width: 100%;
            height: 100vh;
            position: absolute;
            top: 0;
            left: 0;
            z-index: 1;
        }

        .loader-container {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(255, 255, 255, 0.95);
            z-index: 2000;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .container {
            text-align: center;
            z-index: 2;
            padding: 2rem;
            background: transparent;
            transition: transform 0.3s ease;
            position: relative;
        }

        .title {
            font-size: 4rem;
            margin-bottom: 1rem;
            min-height: 4rem;
            cursor: default;
            color: #333;
            opacity: 0;
            transform: translateY(20px);
            animation: fadeInUp 1s ease forwards;
        }

        .title span {
            display: inline-block;
            opacity: 0;
            transform: translateY(20px);
        }

        .subtitle {
            font-size: 1.2rem;
            margin-bottom: 2rem;
            opacity: 0;
            animation: fadeIn 1s ease-in forwards;
            animation-delay: 1s;
        }

        /* Analysis Button */
        .analysis-button {
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 1000;
            padding: 12px 24px;
            background: #2c3e50;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
        }

        .analysis-button:hover {
            background: #34495e;
            transform: translateY(-2px);
        }

        .analysis-button.active {
            background: #e74c3c;
        }

        /* Enhanced Popup Styling */
        .custom-popup {
            max-width: 400px !important;
            max-height: 500px !important;
        }

        .popup-content {
            padding: 15px;
            max-height: 400px;
            overflow-y: auto;
            scrollbar-width: thin;
            scrollbar-color: #888 #f1f1f1;
        }

        .popup-content::-webkit-scrollbar {
            width: 8px;
        }

        .popup-content::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 4px;
        }

        .popup-content::-webkit-scrollbar-thumb {
            background: #888;
            border-radius: 4px;
        }

        .popup-title {
            font-size: 1.5em;
            color: #2c3e50;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #eee;
        }

        .risk-level {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: bold;
        }

        .risk-level.high { background: #ff6b6b; color: white; }
        .risk-level.medium { background: #ffd93d; color: black; }
        .risk-level.low { background: #6dd5ab; color: white; }

        .popup-list {
            margin: 10px 0;
            padding-left: 20px;
        }

        .popup-list li {
            margin: 5px 0;
            line-height: 1.4;
            color: #555;
        }

        /* Ripple Effect */
        .ripple {
            pointer-events: none;
            position: absolute;
            background: rgba(255, 0, 0, 0.4); /* Red background */
            border: 2px solid rgba(255, 0, 0, 0.8); /* Red border */
            border-radius: 50%;
            animation: rippleEffect 2s ease-out infinite;
            z-index: 1000;
        }

        @keyframes rippleEffect {
            0% { transform: scale(0); opacity: 1; }
            100% { transform: scale(1); opacity: 0; }
        }

        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        .weather-section {
            background: #f8f9fa;
            padding: 12px;
            border-radius: 8px;
            margin-top: 15px;
        }

        .weather-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            margin-top: 10px;
        }

        .weather-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    background-color: #fff;
    color: #333;
    font-family: 'Arial', sans-serif;
    height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    overflow: hidden;
}

.container {
    text-align: center;
    z-index: 2;
    padding: 2rem;
    background: transparent;
    transition: transform 0.3s ease;
    position: relative;
}

.container:hover {
    transform: scale(1.02);
}

.title {
    font-size: 4rem;
    margin-bottom: 1rem;
    min-height: 4rem;
    cursor: default;
    color: #333;
}

.title span {
    display: inline-block;
    transition: transform 0.3s ease, color 0.3s ease;
}

.title span:hover {
    transform: translateY(-5px);
    color: #0066cc;
}

.subtitle {
    font-size: 1.2rem;
    margin-bottom: 2rem;
    opacity: 0;
    animation: fadeIn 1s ease-in forwards;
    animation-delay: 3s;
}

.loading-bar {
    width: 300px;
    height: 4px;
    background: rgba(0, 0, 0, 0.1);
    margin: 2rem auto;
    position: relative;
    overflow: hidden;
}

.progress {
    position: absolute;
    left: 0;
    top: 0;
    height: 100%;
    width: 0;
    background: #0066cc;
    animation: progress 3s ease-in-out infinite;
}

.loading-text {
    font-size: 0.8rem;
    letter-spacing: 0.2em;
    animation: blink 1s infinite;
    color: #666;
}

/* Remove all globe-related CSS */
.globe {
    display: none;
}

.globe::before {
    display: none;
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

@keyframes blink {
    50% { opacity: 0.5; }
}

@keyframes progress {
    0% { width: 0; }
    50% { width: 100%; }
    100% { width: 0; }
}

#particles-js {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: 1;
    opacity: 0.5;
}

.cursor-trail {
    position: fixed;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: rgba(128, 128, 128, 0.5);
    pointer-events: none;
    z-index: 3;
    animation: cursorFade 1s ease-out forwards;
}

@keyframes cursorFade {
    0% {
        opacity: 1;
        transform: scale(1);
    }
    100% {
        opacity: 0;
        transform: scale(0);
    }
}

#globe-container {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    z-index: 0;
    opacity: 0.3;
    pointer-events: none;
}

#particles-js {
    z-index: 1;
}

.container {
    position: relative;
    z-index: 2;
} 
#filter-container {
            position: absolute;
            top: 20px;
            right: 20px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            padding: 15px;
            z-index: 1000;
        }
        .filter-checkbox {
            display: flex;
            align-items: center;
            margin: 8px 0;
        }
        .filter-checkbox input {
            margin-right: 10px;
        }
        .filter-checkbox label {
            flex-grow: 1;
        }
    </style>
</head>
<body>

<div class="loader-container" id="loader">
    <div id="particles-js"></div>
    <div id="globe-container"></div>
    <div class="container">
        <h1 class="title"></h1>
        <p class="subtitle">Preparedness and Risk Insights with Smart Mapping</p>
        <div class="loading-bar">
            <div class="progress"></div>
        </div>
        <p class="loading-text">LOADING...</p>
    </div>
    <audio id="typeSound" preload="auto">
        <source src="https://www.soundjay.com/mechanical/sounds/typewriter-key-1.mp3" type="audio/mpeg">
    </audio>
 </div>
 
 <div id="filter-container">
        <div style="font-weight: bold; margin-bottom: 10px; text-align: center;">Water Type Filter</div>
        <div class="filter-checkbox">
            <input type="checkbox" id="river-check" value="river" checked>
            <label for="river-check">River</label>
        </div>
        <div class="filter-checkbox">
            <input type="checkbox" id="stream-check" value="stream" checked>
            <label for="stream-check">Stream</label>
        </div>
        <div class="filter-checkbox">
            <input type="checkbox" id="canal-check" value="canal" checked>
            <label for="canal-check">Canal</label>
        </div>
        <div class="filter-checkbox">
            <input type="checkbox" id="drain-check" value="drain" checked>
            <label for="drain-check">Drain</label>
        </div>
        <div class="filter-checkbox">
            <input type="checkbox" id="ditch-check" value="ditch" checked>
            <label for="ditch-check">Ditch</label>
        </div>
        <div class="filter-checkbox">
            <input type="checkbox" id="other-check" value="other" checked>
            <label for="other-check">Other</label>
        </div>
        
    </div>
    
    <div id="map"></div>
    <button id="analysisButton" class="analysis-button">Start Analysis</button>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/shpjs@latest/dist/shp.js"></script>

    <script>
    class Globe {
    constructor() {
        this.width = 600;
        this.height = 600;
        this.rotation = 0;
        
        // Use createElementNS for SVG
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("width", this.width);
        svg.setAttribute("height", this.height);
        document.getElementById('globe-container').appendChild(svg);
        
        this.svg = d3.select(svg);
        
        // Memoize projection
        this.projection = d3.geoOrthographic()
            .scale(250)
            .center([0, 0])
            .rotate([0, 0])
            .translate([this.width / 2, this.height / 2]);
        
        this.path = d3.geoPath().projection(this.projection);
        
        // Use async/await for data loading
        this.loadWorldData();
    }
    
    async loadWorldData() {
        try {
            const data = await d3.json('https://unpkg.com/world-atlas@2.0.2/countries-110m.json');
            this.worldData = data;
            this.countries = topojson.feature(data, data.objects.countries);
            this.render();
            this.animate();
        } catch (error) {
            console.error('Failed to load world data:', error);
        }
    }
    
    render() {
        // Create elements once and update attributes
        const paths = this.svg.selectAll('path')
            .data(this.countries.features);
            
        paths.enter()
            .append('path')
            .merge(paths)
            .attr('d', this.path)
            .style('fill', '#aaa')
            .style('stroke', '#ddd')
            .style('stroke-width', '0.5');
            
        paths.exit().remove();
    }
    
    animate() {
        if (!this.animationFrame) {
            const animate = () => {
                this.rotation = (this.rotation + 0.5) % 360;
                this.projection.rotate([this.rotation, 0]);
                this.svg.selectAll('path').attr('d', this.path);
                this.animationFrame = requestAnimationFrame(animate);
            };
            animate();
        }
    }

    destroy() {
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
    }
}
        // Performance optimization: Use RequestAnimationFrame for animations
        const animateTitle = () => {
    const particlesConfig = {
        particles: {
            number: { value: 50 }, // Reduced particle count
            color: { value: '#808080' },
            shape: { type: 'circle' },
            opacity: {
                value: 0.5,
                random: true
            },
            size: {
                value: 3,
                random: true
            },
            line_linked: {
                enable: true,
                distance: 150,
                color: '#808080',
                opacity: 0.2,
                width: 1
            },
            move: {
                enable: true,
                speed: 2,
                direction: 'none',
                random: true,
                straight: false,
                out_mode: 'out'
            }
        }
    };

    particlesJS('particles-js', particlesConfig);

    const title = document.querySelector('.title');
    const text = 'P.R.I.S.M.';
    const typeSound = document.getElementById('typeSound');
    let index = 0;

    const playTypeSound = () => {
        const sound = typeSound.cloneNode();
        sound.volume = 0.2;
        sound.play().catch(() => {});
    };

    // Use DocumentFragment for better performance
    const fragment = document.createDocumentFragment();
    const spans = text.split('').map(char => {
        const span = document.createElement('span');
        span.textContent = char;
        span.style.opacity = '0';
        return span;
    });
    
    spans.forEach(span => fragment.appendChild(span));
    title.appendChild(fragment);

    const typeWriter = () => {
        if (index < spans.length) {
            spans[index].style.opacity = '1';
            playTypeSound();
            index++;
            setTimeout(typeWriter, 200);
        }
    };

    // Start typing after DOM is ready
    requestAnimationFrame(typeWriter);

    // Optimize cursor trail
    let cursorTimeout;
    const cursorTrails = [];
    
    document.addEventListener('mousemove', (e) => {
        if (cursorTimeout) return;
        
        cursorTimeout = setTimeout(() => {
            cursorTimeout = null;
        }, 50);

        const cursor = document.createElement('div');
        cursor.className = 'cursor-trail';
        cursor.style.left = e.pageX + 'px';
        cursor.style.top = e.pageY + 'px';
        document.body.appendChild(cursor);
        
        cursorTrails.push(cursor);
        if (cursorTrails.length > 5) {
            const oldCursor = cursorTrails.shift();
            oldCursor.remove();
        }

        setTimeout(() => {
            cursor.remove();
            const index = cursorTrails.indexOf(cursor);
            if (index > -1) cursorTrails.splice(index, 1);
        }, 1000);
    }, { passive: true });
};


        class MapApplication {
            constructor() {
                this.map = null;
                this.loader = document.getElementById('loader');
                this.isAnalysisMode = false;
                this.activeRipples = [];
                this.initialize();
            }

            initialize() {
                new Globe();
                this.initializeMap();
                this.loadShapefile();
                this.initializeAnalysisButton();
                this.setupFilterListeners();
                
            }

            initializeMap() {
                this.map = L.map('map').setView([45.9432, 24.9668], 6);
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(this.map);
            }
            
            setupFilterListeners() {
                const waterTypes = ['river', 'stream', 'canal', 'drain', 'other', 'ditch'];
                waterTypes.forEach(type => {
                    document.getElementById(`${type}-check`).addEventListener('change', () => {
                        this.filterWaterways();
                    });
                });
            }
        
            initializeAnalysisButton() {
                const button = document.getElementById('analysisButton');
                button.addEventListener('click', () => {
                    this.isAnalysisMode = !this.isAnalysisMode;
                    button.classList.toggle('active');
                    button.textContent = this.isAnalysisMode ? 'Cancel Analysis' : 'Start Analysis';
                    
                    if (this.isAnalysisMode) {
                        this.map.on('click', this.handleMapClick.bind(this));
                    } else {
                        this.map.off('click');
                        this.clearRipples();
                    }
                });
            }
            
            destroy() {
                this.map.remove();
                if (this.globe) {
                    this.globe.destroy();
                }
                this.clearRipples();
            }

            async loadShapefile() {
                try {
                    const response = await fetch('https://bim-2025.onrender.com/shapefile/waterways_romania.zip');
                    if (!response.ok) throw new Error('Failed to fetch shapefile');

                    const arrayBuffer = await response.arrayBuffer();
                    const geojsonArray = await shp.parseZip(arrayBuffer);
                    await this.processGeoJSON(geojsonArray);
                    
                    this.fadeOutLoader();
                } catch (error) {
                    console.error('Error loading shapefile:', error);
                    document.querySelector('.loading-text').textContent = 'Error loading data';
                }
            }

            fadeOutLoader() {
                animateTitle();
                setTimeout(() => this.loader.remove(), 6000);
            }

            async processGeoJSON(geojsonArray) {
            const data = Array.isArray(geojsonArray) ? geojsonArray[0] : geojsonArray;
            if (!data || !data.features) throw new Error('Invalid GeoJSON data');
            
            // Color mapping for different water types
            const waterTypeColors = {
                'river': '#3388ff',
                'stream': '#2ecc71', 
                'canal': '#e74c3c',
                'drain': '#f39c12',
                'other': '#9b59b6',
                'ditch': '#34495e'
            };

            this.waterLayer = L.geoJSON(data, {
                style: (feature) => {
                    const waterType = feature.properties.waterway || 'other';
                    return {
                        color: waterTypeColors[waterType] || '#34495e',
                        weight: 3,
                        opacity: 0.7
                    };
                }
            }).addTo(this.map);

            this.filterWaterways();
        }
        
        filterWaterways() {
            if (!this.waterLayer) return;

            this.waterLayer.eachLayer(layer => {
                // Use 'waterway' or fallback to 'other' if not present
                const waterType = layer.feature.properties.waterway || 'other';
                const waterTypes = ['river', 'stream', 'canal', 'drain', 'other', 'ditch']
                if (waterTypes.includes(waterType)) {
    
                    const isChecked = document.getElementById(`${waterType}-check`).checked;
                    
                    
                    if (isChecked) {
                        layer.addTo(this.map);
                    } else {
                        this.map.removeLayer(layer);
                    }
                }
            });
        }

            createRippleEffect(latlng) {
                const point = this.map.latLngToContainerPoint(latlng);
                const rippleSize = 200;
                
                [0, 0.4, 0.8].forEach(delay => {
                    const ripple = L.DomUtil.create('div', 'ripple');
                    Object.assign(ripple.style, {
                        left: `${point.x - rippleSize/2}px`,
                        top: `${point.y - rippleSize/2}px`,
                        width: `${rippleSize}px`,
                        height: `${rippleSize}px`,
                        animationDelay: `${delay}s`
                    });
                    
                    this.map.getContainer().appendChild(ripple);
                    this.activeRipples.push(ripple);
                });
            }

            clearRipples() {
                this.activeRipples.forEach(ripple => ripple.remove());
                this.activeRipples = [];
            }

            createPopupContent(data) {
                return `
                    <div class="popup-content">
                        <h3 class="popup-title">Flood Risk Analysis</h3>
                        <p><strong>Risk Level:</strong> <span class="risk-level ${data.riskLevel.toLowerCase()}">${data.riskLevel}</span></p>
                        <p><strong>Risk Score:</strong> ${data.riskScore}</p>
                        
                        <h4>Main Factors</h4>
                        <ul class="popup-list">
                            ${data.mainFactors.map(factor => `<li>${factor}</li>`).join('')}
                        </ul>

                        <div class="weather-section">
                            <h4>Weather Conditions</h4>
                            <div class="weather-grid">
                                <div class="weather-item">
                                    <span>🌡️</span>
                                    <span>${data.weather.temperature}°C</span>
                                </div>
                                <div class="weather-item">
                                    <span>💧</span>
                                    <span>${data.weather.precipitation}mm</span>
                                </div>
                                <div class="weather-item">
                                    <span>💨</span>
                                    <span>${data.weather.wind_speed} km/h</span>
                                </div>
                                <div class="weather-item">
                                    <span>🌤️</span>
                                    <span>${data.weather.condition}</span>
                                </div>
                            </div>
                        </div>
                        
                        <h4>Concerns</h4>
                        <ul class="popup-list">
                            ${data.concerns.map(concern => `<li>${concern}</li>`).join('')}
                        </ul>
                        
                        <h4>Explanation</h4>
                        <ul class="popup-list">
                            <li>${data.explanation}</li>
                        </ul>
                        
                        <h4>Recommendations</h4>
                        <ul class="popup-list">
                            ${data.recommendations.map(recommendation => `<li>${recommendation}</li>`).join('')}
                        </ul>
                    </div>
                `;
            }

            async handleMapClick(e) {
                if (!this.isAnalysisMode) return;
                
                this.createRippleEffect(e.latlng);

                try {
                    const response = await fetch('https://bim-2025.onrender.com/api/analyze', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            point: {
                                lat: e.latlng.lat,
                                lng: e.latlng.lng
                            },
                            radius: 2500
                        })
                    });

                    if (!response.ok) throw new Error('API request failed');
                    const data = await response.json();

                    this.clearRipples();
                    
                    const popup = L.popup({
                        maxWidth: 400,
                        className: 'custom-popup'
                    })
                        .setLatLng(e.latlng)
                        .setContent(this.createPopupContent(data))
                        .openOn(this.map);

                } catch (error) {
                    console.error('Analysis error:', error);
                    this.clearRipples();
                    L.popup()
                        .setLatLng(e.latlng)
                        .setContent('<div class="popup-content">Error analyzing data.</div>')
                        .openOn(this.map);
                }
            }
        }

        // Initialize application
        document.addEventListener('DOMContentLoaded', () => new MapApplication());
    </script>
</body>
</html>



"""

    (STATIC_DIR / "index.html").write_text(html_content)


init_static_files()
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def read_root():
    """Serve the main HTML page"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/shapefile/{filename}")
async def get_shapefile(filename: str):
    from pathlib import Path

    file_path = Path("data") / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File {filename} not found")

    # Set proper headers for binary file transfer
    headers = {
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Access-Control-Expose-Headers': 'Content-Disposition'
    }

    return FileResponse(
        path=file_path,
        headers=headers,
        media_type='application/octet-stream'
    )


@app.post("/api/analyze")
async def analyze_location(request: AnalysisRequest):
    """Analyze flood risk for a location"""
    try:
        data_store = SpatialDataStore()
        # Gather all required data
        weather = await get_weather_forecast(request.point)
        elevation_data = await get_elevation_data(request.point)
        nearby_waterways = data_store.find_nearby_waterways(request.point, request.radius)
        # flooding_data = data_store.get_flooding_data(request.point, request.radius)

        # Prepare analysis data
        analysis_data = {
            "location": {
                "latitude": request.point.lat,
                "longitude": request.point.lng,
                "elevation": {
                    "value": elevation_data,
                    "unit": "meters"
                }
            },
            "weather": {
                "current": {
                    "temperature": weather["current"]["temp_c"],
                    "precipitation": weather["current"]["precip_mm"],
                    "humidity": weather["current"]["humidity"],
                    "condition": weather["current"]["condition"]["text"],
                    "wind_speed": weather["current"]["wind_kph"],
                    "pressure": weather["current"]["pressure_mb"]
                },
                "forecast": [
                    {
                        "date": day["date"],
                        "precipitation_mm": day["day"]["totalprecip_mm"],
                        "avg_temp_c": day["day"]["avgtemp_c"],
                        "max_wind_kph": day["day"]["maxwind_kph"],
                        "chance_of_rain": day["day"]["daily_chance_of_rain"]
                    }
                    for day in weather["forecast"]["forecastday"]
                ]
            },
            "waterways": nearby_waterways,
            "flooding_data": None,
            "analysis_radius": request.radius,
            "terrain": {
                "elevation": elevation_data,
                "elevation_relative_to_waterways": calculate_relative_elevation(elevation_data, nearby_waterways),
                "waterway_count": len(nearby_waterways),
                "waterway_types": list(set(w["type"] for w in nearby_waterways))
            }
        }

        # Get AI analysis
        risk_analysis = await analyze_with_openai(analysis_data)
        return risk_analysis

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def get_weather_forecast(point: Point) -> Dict[str, Any]:
    """Get weather forecast from API"""
    try:
        url = f"https://api.weatherapi.com/v1/forecast.json"
        params = {
            "key": WEATHER_CONFIG["api_key"],
            "q": f"{point.lat},{point.lng}",
            "days": WEATHER_CONFIG["forecast_days"]
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(status_code=response.status_code, detail="Weather API error")
    except Exception as e:
        return {
            "current": {
                "temp_c": 20,
                "precip_mm": 0,
                "humidity": 50,
                "condition": {"text": "Unknown"}
            },
            "forecast": {
                "forecastday": [{
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "day": {
                        "totalprecip_mm": 0,
                        "avgtemp_c": 20
                    }
                } for _ in range(7)]
            }
        }


async def get_elevation_data(point: Point) -> float:
    """Get elevation data from Maptiler API"""
    try:
        zoom = 12
        lat, lng = point.lat, point.lng
        n = 2 ** zoom
        xtile = int((lng + 180) / 360 * n)
        ytile = int((1 - np.log(np.tan(np.radians(lat)) + 1 / np.cos(np.radians(lat))) / np.pi) / 2 * n)

        url = f"https://api.maptiler.com/tiles/terrain-rgb/{zoom}/{xtile}/{ytile}.png"
        params = {"key": "mcUdBlpX6o8IFQ03OMfE"}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                return 100  # Default elevation for example
            else:
                raise HTTPException(status_code=response.status_code, detail="Elevation API error")
    except Exception as e:
        return 100  # Default elevation


async def analyze_with_openai(data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze data using OpenAI API"""
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a flood risk analysis expert. Analyze the provided data including:\n"
                    "- Weather conditions and forecasts\n"
                    "- Terrain elevation and nearby waterways\n"
                    "- Existing buildings and infrastructure\n"
                    "- Known flood-prone areas and inundation zones\n"
                    "- Land use patterns\n"
                    "Provide a comprehensive flood risk assessment considering all these factors.\n"
                    "Always respond with a valid JSON object containing:\n"
                    "- riskLevel (LOW/MEDIUM/HIGH)\n"
                    "- riskScore (0-1)\n"
                    "- mainFactors (array of key risk factors)\n"
                    "- concerns (array of specific concerns)\n"
                    "- recommendations (array of actionable recommendations)\n"
                    "- explanation (detailed analysis string)\n"
                )
            },
            {
                "role": "user",
                "content": json.dumps(data)
            }
        ]

        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages
        )

        response_data = json.loads(response.choices[0].message.content)
        response_data["weather"] = data["weather"]["current"]
        return response_data

    except Exception as e:
        print (f"Aaaaaaaaaaaaaaa {e}")
        return generate_local_analysis(data)


def generate_local_analysis(data: Dict[str, Any]) -> Dict[str, Any]:
    """Generate local analysis when API is unavailable"""
    risk_score = 0
    factors = []
    concerns = []
    recommendations = []

    # Analyze waterways
    if data['waterways']:
        closest_waterway = min(w['distance'] for w in data['waterways'])
        if closest_waterway < 500:
            risk_score += 0.3
            factors.append('Close proximity to waterway')
            concerns.append(f"Waterway within {round(closest_waterway)}m")

    # Analyze flooding data
    if data['flooding_data']:
        if data['flooding_data']['known_inundation_areas'] > 0:
            risk_score += 0.4
            factors.append('Located in known inundation area')
            concerns.append('Historical flooding recorded in this area')

    # Analyze elevation
    if data['terrain']['elevation'] < FLOOD_RISK_CONFIG['elevation_threshold']:
        risk_score += 0.3
        factors.append('Low elevation relative to waterways')
        concerns.append('Area at risk during heavy rainfall')

    # Determine risk level
    risk_level = 'LOW'
    if risk_score > 0.7:
        risk_level = 'HIGH'
        recommendations.append('Consider flood protection measures')
    elif risk_score > 0.3:
        risk_level = 'MEDIUM'
        recommendations.append('Monitor water levels during rainy seasons')

    return {
        "riskLevel": risk_level,
        "riskScore": min(1, risk_score),
        "mainFactors": factors,
        "concerns": concerns,
        "recommendations": recommendations,
        "explanation": f"Analysis based on {len(factors)} main risk factors including proximity to waterways, historical flooding data, and terrain characteristics."
    }


def calculate_relative_elevation(elevation: float, waterways: List[Dict[str, Any]]):
    """Calculate elevation relative to nearby waterways"""
    if not waterways:
        return None
    waterway_elevations = [w['properties'].get('ele', elevation) for w in waterways]
    return elevation - min(waterway_elevations)


if __name__ == "__main__":
    import uvicorn

    # data_store = SpatialDataStore()
    # # data_store.get_waterway()
    # gdf = gpd.read_file("/Users/andreihilote/workspace/bim2025/waterways_romania/hotosm_rou_waterways_lines_shp.shp")
    # #
    # # # Convert to GeoJSON and store in database
    # geojson_data = json.loads(gdf.to_json())
    # #
    # #
    # data_store.store_flooding_data(geojson_data)
    # #
    # data_store.store_waterway_data(geojson_data)

    uvicorn.run(app, host="0.0.0.0", port=8000)