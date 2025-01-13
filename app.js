const API_RATE_LIMIT = {
    requestsPerMinute: 3,
    requestQueue: [],
    lastRequestTime: 0
};

const map = L.map('map', {
    preferCanvas: true,
    zoomSnap: 0.5,
    zoomDelta: 0.5,
    wheelDebounceTime: 150,
    wheelPxPerZoomLevel: 120,
    maxZoom: 18,
    minZoom: 5
});

map.setView([46.0, 25.0], 7); // Center on Romania

const baseMap = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors, © CARTO',
    subdomains: 'abcd',
    maxZoom: 18,
    minZoom: 5,
    crossOrigin: true,
    tileSize: 256,
    updateWhenIdle: true,
    updateWhenZooming: false,
    keepBuffer: 2,
    tileOptions: {
        crossOrigin: 'anonymous',
        referrerPolicy: 'no-referrer'
    }
}).addTo(map);

const terrainLayer = L.tileLayer('https://api.maptiler.com/tiles/terrain-rgb/{z}/{x}/{y}.png?key=mcUdBlpX6o8IFQ03OMfE', {
    tileSize: 256,
    maxZoom: 18,
    minZoom: 5,
    key: 'mcUdBlpX6o8IFQ03OMfE'
});

const performanceOptions = {
    renderer: L.canvas({ padding: 0.5 }),
    interactive: false,
    bubblingMouseEvents: false,
    pane: 'overlayPane'
};

const waterwayLayers = {
    river: L.featureGroup(null, performanceOptions),
    stream: L.featureGroup(null, performanceOptions),
    canal: L.featureGroup(null, performanceOptions),
    drain: L.featureGroup(null, performanceOptions),
    other: L.featureGroup(null, performanceOptions)
};

const layerFeatures = {
    river: null,
    stream: null,
    canal: null,
    drain: null,
    other: null,
    buildings: null,
    transportation: null,
    landuse: null,
    inundation: null
};

const waterwayStyles = {
    river: {
        color: '#0077be',
        weight: 3,
        opacity: 0.8
    },
    stream: {
        color: '#ff4400',
        weight: 2,
        opacity: 0.7
    },
    canal: {
        color: '#9933cc',
        weight: 2.5,
        opacity: 0.8
    },
    drain: {
        color: '#00cc44',
        weight: 1.5,
        opacity: 0.6
    },
    other: {
        color: '#ff9900',
        weight: 1.5,
        opacity: 0.7
    }
};

const floodRiskConfig = {
    elevationThreshold: 5, // meters above nearest waterway
    rainfallThreshold: 50, // mm per day
    soilSaturationThreshold: 0.8, // 0-1 scale
    waterLevelThreshold: 2 // meters above normal
};

const weatherConfig = {
    apiKey: '4e203ee12a8247af85f122549240612',
    forecastDays: 7,
    updateInterval: 3600000 // 1 hour
};

const floodRiskStyles = {
    high: {
        color: '#ff0000',
        fillColor: '#ff0000',
        fillOpacity: 0.3,
        weight: 2
    },
    medium: {
        color: '#ffa500',
        fillColor: '#ffa500',
        fillOpacity: 0.3,
        weight: 2
    },
    low: {
        color: '#00ff00',
        fillColor: '#00ff00',
        fillOpacity: 0.3,
        weight: 2
    }
};

let currentFeatures = null;

let shapefileComponents = new Map();

const layerQueue = new Set();

const CHUNK_SIZE = 15;
const PROCESS_DELAY = 100;
const UPDATE_UI_FREQUENCY = 1;
const MAX_FEATURES_PER_LAYER = 5000;

const MAX_VISIBLE_FEATURES = 2000;
const MIN_ZOOM_ALL_FEATURES = 12;

const processedLayers = new Map();

const THROTTLE_DELAY = 100;
let throttleTimer;

let isProcessingLayer = false;

function throttledUpdate() {
    if (!throttleTimer) {
        throttleTimer = setTimeout(() => {
            updateVisibleFeatures();
            throttleTimer = null;
        }, THROTTLE_DELAY);
    }
}

map.on('zoomend moveend', throttledUpdate);

function updateVisibleFeatures() {
    const zoom = map.getZoom();
    const bounds = map.getBounds();
    const padding = 0.1;
    const extendedBounds = bounds.pad(padding);

    Object.entries(waterwayLayers).forEach(([layerName, layer]) => {
        if (map.hasLayer(layer) && layer.allFeatures) {
            const visibleFeatures = optimizeFeatures(
                getVisibleFeatures(layer.allFeatures, extendedBounds, MAX_FEATURES_PER_LAYER),
                zoom
            );

            layer.clearLayers();
            
            const batchLayer = L.geoJSON(visibleFeatures, {
                style: waterwayStyles[layerName],
                interactive: true,
                onEachFeature: (feature, layer) => {
                    layer.on('click', () => {
                        if (!layer.getPopup()) {
                            const popupContent = createPopupContent(feature.properties);
                            layer.bindPopup(popupContent).openPopup();
                        }
                    });
                }
            });

            layer.addLayer(batchLayer);
        }
    });
}

function optimizeFeatures(features, zoom) {
    if (zoom < 10) {
        return features.filter(f => 
            f.properties.waterway === 'river' || 
            (f.properties.width && f.properties.width > 5)
        ).map(f => simplifyGeometry(f, 0.001 * Math.pow(2, 10 - zoom)));
    } else if (zoom < 13) {
        return features.map(f => simplifyGeometry(f, 0.0001 * Math.pow(2, 13 - zoom)));
    }
    return features;
}

function simplifyGeometry(feature, tolerance) {
    if (!feature.geometry || !feature.geometry.coordinates) return feature;
    
    const simplified = {
        ...feature,
        geometry: {
            ...feature.geometry,
            coordinates: feature.geometry.coordinates.map(coords => 
                typeof coords[0] === 'number' ? coords : 
                coords.filter((_, i) => i % Math.ceil(1/tolerance) === 0)
            )
        }
    };
    return simplified;
}

async function displayGeoJSON(geojson, filename) {
    try {
        // For flooding area zip files, we get an array of GeoJSON objects
        if (Array.isArray(geojson)) {
            // Validate that each item in the array has features
            const validGeojsons = geojson.filter(item => item && item.features && item.features.length > 0);
            if (validGeojsons.length === 0) {
                throw new Error('No valid features found in the files');
            }
            // Create a combined GeoJSON object
            const combinedGeojson = {
                type: 'FeatureCollection',
                features: [],
                fileName: filename // Keep the original filename
            };
            // Add all features from each GeoJSON object
            validGeojsons.forEach(item => {
                combinedGeojson.features.push(...item.features);
                // Store the original filename in each feature for layer identification
                item.features.forEach(feature => {
                    feature.properties.sourceFile = item.fileName;
                });
            });
            geojson = combinedGeojson;
        }

        if (!geojson || !geojson.features) {
            console.error('Invalid GeoJSON structure:', geojson);
            throw new Error('Invalid GeoJSON structure');
        }

        const loader = document.getElementById('loader');
        const progressText = document.createElement('p');
        loader.appendChild(progressText);

        try {
            console.log(`Processing ${filename} with ${geojson.features.length} features`);
            
            if (filename.toLowerCase().includes('flooding_area')) {
                await processFloodingData(geojson, progressText);
            } else {
                await processWaterwayData(geojson, progressText);
            }

            createLayerControl(filename);

        } catch (processingError) {
            console.error('Error processing data:', processingError);
            throw processingError;
        } finally {
            if (loader.contains(progressText)) {
                loader.removeChild(progressText);
            }
            loader.classList.add('hidden');
        }

    } catch (error) {
        console.error('Error in displayGeoJSON:', error);
        document.getElementById('loader').classList.add('hidden');
        throw error;
    }
}

function createLayerControl(filename) {
    const controlId = `control-${filename.replace(/[^a-z0-9]/gi, '-')}`;
    let existingControl = document.querySelector(`#${controlId}`);
    
    if (existingControl) {
        existingControl.remove();
    }

    const control = L.control({ position: 'topright' });

    control.onAdd = function() {
        const div = L.DomUtil.create('div', 'leaflet-control-layers custom-layer-control');
        div.id = controlId;
        div.style.padding = '10px';
        div.style.background = 'white';
        div.style.borderRadius = '4px';
        div.style.marginBottom = '10px';

        L.DomEvent.disableClickPropagation(div);

        div.innerHTML = `
            <div class="panel-header" style="cursor: pointer; margin-bottom: 5px;">
                <span class="collapse-icon">▼</span>
                <h4 style="display: inline; margin: 0;">${filename}</h4>
            </div>
            <div class="panel-content" style="display: ${activePanels.has(controlId) ? 'block' : 'none'};">
                <div id="layer-loading" class="hidden text-sm text-gray-600 mb-2">
                    <div class="spinner-border animate-spin inline-block w-4 h-4 border-2 rounded-full mr-2"></div>
                    <span class="loading-text">Loading layer...</span>
                    <div class="progress-bar mt-1" style="height: 3px; background: #eee;">
                        <div class="progress" style="width: 0%; height: 100%; background: #3b82f6; transition: width 0.3s;"></div>
                    </div>
                </div>
                <div class="layers-list"></div>
            </div>
        `;

        const header = div.querySelector('.panel-header');
        const content = div.querySelector('.panel-content');
        const icon = div.querySelector('.collapse-icon');
        
        header.addEventListener('click', () => {
            const isVisible = content.style.display !== 'none';
            content.style.display = isVisible ? 'none' : 'block';
            icon.textContent = isVisible ? '▶' : '▼';
            if (isVisible) {
                activePanels.delete(controlId);
            } else {
                activePanels.add(controlId);
            }
        });

        const layersList = div.querySelector('.layers-list');
        if (filename.toLowerCase().includes('flooding_area')) {
            addFloodingLayerToggles(layersList, filename);
        } else {
            addWaterwayLayerToggles(layersList, filename);
        }

        return div;
    };

    control.addTo(map);
}

function addWaterwayLayerToggles(container, filename) {
    const layerNames = {
        river: 'Rivers',
        stream: 'Streams',
        canal: 'Canals',
        drain: 'Drains',
        other: 'Other Waterways'
    };

    Object.entries(layerNames).forEach(([key, label]) => {
        const checked = key === 'river' ? 'checked' : '';
        container.innerHTML += `
            <div style="margin-bottom:5px">
                <label>
                    <input type="checkbox" ${checked} data-layer="${key}" data-file="${filename}">
                    <span style="display:inline-block; width:20px; height:3px; background-color:${waterwayStyles[key].color}; margin:0 5px"></span>
                    ${label}
                    <span class="feature-count text-xs text-gray-500"></span>
                </label>
            </div>`;
    });

    container.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
        checkbox.addEventListener('change', async function() {
            const layerName = this.dataset.layer;
            const fileKey = this.dataset.file;
            const layerKey = `${fileKey}-${layerName}`;
            
            if (this.checked) {
                activeLayerTypes[layerName] = true;
                
                let processedLayer = processedLayersByFile.get(layerKey);
                
                if (!processedLayer && layerFeatures[layerName]) {
                    const loadingIndicator = container.closest('.custom-layer-control').querySelector('#layer-loading');
                    loadingIndicator.classList.remove('hidden');
                    
                    try {
                        processedLayer = await processFeatures(
                            layerFeatures[layerName], 
                            layerName, 
                            loadingIndicator.querySelector('.loading-text')
                        );
                        processedLayersByFile.set(layerKey, processedLayer);
                    } finally {
                        loadingIndicator.classList.add('hidden');
                    }
                }

                if (processedLayer) {
                    waterwayLayers[layerName].clearLayers();
                    waterwayLayers[layerName].addLayer(processedLayer);
                    waterwayLayers[layerName].addTo(map);
                }
            } else {
                activeLayerTypes[layerName] = false;
                map.removeLayer(waterwayLayers[layerName]);
            }
        });
    });
}

function addFloodingLayerToggles(container, filename) {
    const layerNames = {
        buildings: 'Buildings',
        transportation: 'Transportation',
        landuse: 'Land Use',
        inundation: 'Inundation Extent'
    };

    Object.entries(layerNames).forEach(([key, label]) => {
        const checked = key === 'buildings' ? 'checked' : '';
        container.innerHTML += `
            <div style="margin-bottom:5px">
                <label>
                    <input type="checkbox" ${checked} data-layer="${key}">
                    <span style="display:inline-block; width:20px; height:3px; background-color:${floodingStyles[key].color}; margin:0 5px"></span>
                    ${label}
                </label>
            </div>`;
    });

    container.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
        checkbox.addEventListener('change', async function() {
            const layerName = this.dataset.layer;
            const layerKey = `flooding_area-${layerName}`;
            
            if (this.checked) {
                let processedLayer = processedLayersByFile.get(layerKey);
                
                if (!processedLayer && layerFeatures[layerName]) {
                    const loadingIndicator = container.closest('.custom-layer-control').querySelector('#layer-loading');
                    loadingIndicator.classList.remove('hidden');
                    
                    try {
                        console.log(`Processing ${layerName} layer on demand...`);
                        processedLayer = await processFeatures(layerFeatures[layerName], layerName, loadingIndicator.querySelector('.loading-text'));
                        processedLayersByFile.set(layerKey, processedLayer);
                    } finally {
                        loadingIndicator.classList.add('hidden');
                    }
                }

                if (processedLayer) {
                    floodingLayers[layerName].clearLayers();
                    floodingLayers[layerName].addLayer(processedLayer);
                    floodingLayers[layerName].addTo(map);
                    console.log(`Activated ${layerName} layer`);
                } else {
                    console.warn(`No features found for ${layerName}`);
                }
            } else {
                map.removeLayer(floodingLayers[layerName]);
                console.log(`Deactivated ${layerName} layer`);
            }
        });
    });
}

async function handleShapefileZip(file) {
    try {
        console.log('Processing file:', file.name);

        if (file.name.toLowerCase().endsWith('.zip')) {
            const arrayBuffer = await readFileAsArrayBuffer(file);
            console.log('File loaded into buffer, size:', arrayBuffer.byteLength);
            
            const geojsonArray = await shp.parseZip(arrayBuffer);
            console.log('Parsed GeoJSON array:', geojsonArray);
            
            if (!geojsonArray) {
                throw new Error('Failed to parse shapefile: No data returned');
            }

            if (file.name.toLowerCase().includes('flooding_area')) {
                // Process all files in the flooding area zip
                await displayGeoJSON(geojsonArray, file.name);
            } else {
                // For waterways, just take the first file
                const data = Array.isArray(geojsonArray) ? geojsonArray[0] : geojsonArray;
                await displayGeoJSON(data, file.name);
            }
            return;
        }

        const extension = file.name.split('.').pop().toLowerCase();
        console.log('Processing individual file with extension:', extension);
        
        shapefileComponents.set(extension, file);

        if (shapefileComponents.has('shp') && shapefileComponents.has('dbf')) {
            console.log('Have minimum required files, processing...');
            
            const shpBuffer = await readFileAsArrayBuffer(shapefileComponents.get('shp'));
            const dbfBuffer = await readFileAsArrayBuffer(shapefileComponents.get('dbf'));
            
            const geojson = await shp.combine([
                await shp.parseShp(shpBuffer),
                await shp.parseDbf(dbfBuffer)
            ]);

            if (!geojson) {
                throw new Error('Failed to parse shapefile components: No data returned');
            }

            await displayGeoJSON(geojson, file.name);
            shapefileComponents.clear();
        }
    } catch (error) {
        console.error('Detailed error in handleShapefileZip:', error);
        throw error;
    }
}

const floodingLayers = {
    buildings: L.featureGroup(null, performanceOptions),
    transportation: L.featureGroup(null, performanceOptions),
    landuse: L.featureGroup(null, performanceOptions),
    inundation: L.featureGroup(null, performanceOptions)
};

const floodingStyles = {
    buildings: {
        color: '#ff0000',
        weight: 1,
        opacity: 0.8,
        fillColor: '#ff0000',
        fillOpacity: 0.3
    },
    transportation: {
        color: '#000000',
        weight: 2,
        opacity: 0.8,
        fillColor: '#000000',
        fillOpacity: 0.3
    },
    landuse: {
        color: '#90EE90',
        weight: 1,
        opacity: 0.6,
        fillColor: '#90EE90',
        fillOpacity: 0.2
    },
    inundation: {
        color: '#0000FF',
        weight: 1,
        opacity: 0.7,
        fillColor: '#0000FF',
        fillOpacity: 0.3
    }
};

async function processFloodingData(features, progressText) {
    progressText.textContent = 'Processing flooding data...';
    
    try {
        const layerMappings = {
            'P01_REF_Buildings': 'buildings',
            'P01_REF_Transportation': 'transportation',
            'P02_LULC': 'landuse',
            'P03_MOD_Inundation': 'inundation'
        };

        // Just group features by layer type without processing
        const groupedFeatures = {};
        
        features.features.forEach(feature => {
            const sourceFile = feature.properties.sourceFile || '';
            let layerType = null;
            
            for (const [pattern, type] of Object.entries(layerMappings)) {
                if (sourceFile.includes(pattern)) {
                    layerType = type;
                    break;
                }
            }

            if (layerType) {
                if (!groupedFeatures[layerType]) {
                    groupedFeatures[layerType] = [];
                }
                groupedFeatures[layerType].push(feature);
            }
        });

        // Store raw features for later processing
        for (const [layerType, features] of Object.entries(groupedFeatures)) {
            console.log(`Found ${features.length} ${layerType} features`);
            // Store features in the global layerFeatures object
            layerFeatures[layerType] = features;
        }

        // Only process buildings if it's the default visible layer
        if (groupedFeatures.buildings && activeLayerTypes.buildings) {
            const processedLayer = await processFeatures(groupedFeatures.buildings, 'buildings', progressText);
            const layerKey = `flooding_area-buildings`;
            processedLayersByFile.set(layerKey, processedLayer);
            
            floodingLayers.buildings.clearLayers();
            floodingLayers.buildings.addLayer(processedLayer);
            floodingLayers.buildings.addTo(map);
            console.log(`Added buildings layer to map`);

            // Fit map to buildings layer
            const bounds = floodingLayers.buildings.getBounds();
            if (bounds.isValid()) {
                map.fitBounds(bounds, { padding: [50, 50] });
            }
        }

    } catch (error) {
        console.error('Error in processFloodingData:', error);
        throw error;
    }
}

function readFileAsArrayBuffer(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsArrayBuffer(file);
    });
}

document.getElementById('fileInput').addEventListener('change', async (e) => {
    const files = e.target.files;
    if (!files.length) return;

    document.getElementById('loader').classList.remove('hidden');
    console.log('Processing files:', Array.from(files).map(f => f.name));

    try {
        shapefileComponents.clear();

        for (const file of files) {
            console.log('Processing file:', file.name);
            
            try {
                await handleShapefileZip(file);
            } catch (error) {
                console.error(`Error processing file ${file.name}:`, error);
                throw error;
            }
        }
    } catch (error) {
        console.error('Error processing files:', error);
        alert(`Error processing files: ${error.message}\nCheck the console for more details.`);
    } finally {
        document.getElementById('loader').classList.add('hidden');
    }
});

async function handleKMLFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        const kmlText = e.target.result;
        const parser = new DOMParser();
        const kml = parser.parseFromString(kmlText, 'text/xml');
        const geojson = toGeoJSON.kml(kml);
        displayGeoJSON(geojson);
    };
    reader.readAsText(file);
}

async function handleKMZFile(file) {
    const zip = new JSZip();
    const zipContent = await zip.loadAsync(file);
    
    const kmlFile = Object.values(zipContent.files).find(file => 
        file.name.toLowerCase().endsWith('.kml')
    );

    if (!kmlFile) {
        throw new Error('No KML file found in KMZ');
    }

    const kmlText = await kmlFile.async('text');
    const parser = new DOMParser();
    const kml = parser.parseFromString(kmlText, 'text/xml');
    const geojson = toGeoJSON.kml(kml);
    await displayGeoJSON(geojson);
}

map.on('zoomend moveend', function() {
    if (updateTimeout) clearTimeout(updateTimeout);
    
    updateTimeout = setTimeout(() => {
        const zoom = map.getZoom();
        const bounds = map.getBounds();

        Object.entries(waterwayLayers).forEach(([layerName, layer]) => {
            if (map.hasLayer(layer) && layer.allFeatures) {
                const visibleFeatures = optimizeFeatures(
                    getVisibleFeatures(layer.allFeatures, bounds, MAX_FEATURES_PER_LAYER),
                    zoom
                );

                layer.clearLayers();
                
                for (let i = 0; i < visibleFeatures.length; i += CHUNK_SIZE) {
                    const chunk = visibleFeatures.slice(i, i + CHUNK_SIZE);
                    const chunkLayer = L.geoJSON(chunk, {
                        style: waterwayStyles[layerName],
                        onEachFeature: (feature, layer) => {
                            layer.on('click', () => {
                                if (!layer.getPopup()) {
                                    const popupContent = createPopupContent(feature.properties);
                                    layer.bindPopup(popupContent).openPopup();
                                }
                            });
                        }
                    });
                    layer.addLayer(chunkLayer);
                }
            }
        });
    }, 250);
});

function optimizeFeatures(features, zoom) {
    if (zoom < 10) {
        return features.filter(f => 
            f.properties.waterway === 'river' || 
            (f.properties.width && f.properties.width > 5)
        );
    }
    return features;
}

function reduceFeatures(features, maxFeatures) {
    if (!features || features.length <= maxFeatures) return features;
    
    const step = Math.ceil(features.length / maxFeatures);
    return features.filter((_, index) => index % step === 0);
}

async function processFeatures(features, layerType, progressText) {
    if (!features || !features.length) {
        console.warn(`No features to process for ${layerType}`);
        return L.featureGroup();
    }

    features = reduceFeatures(features, MAX_FEATURES_PER_LAYER);
    
    const layerGroup = L.featureGroup();
    layerGroup.allFeatures = features;

    const totalFeatures = features.length;
    let processed = 0;

    // Determine which style to use based on layer type
    const style = floodingStyles[layerType] || waterwayStyles[layerType] || {};

    while (processed < totalFeatures) {
        const chunk = features.slice(processed, processed + CHUNK_SIZE);
        const chunkLayer = L.geoJSON(chunk, {
            style: style,
            onEachFeature: (feature, layer) => {
                layer.on('click', () => {
                    if (!layer.getPopup()) {
                        const popupContent = createPopupContent(feature.properties);
                        layer.bindPopup(popupContent).openPopup();
                    }
                });
            }
        });

        layerGroup.addLayer(chunkLayer);
        processed += chunk.length;

        if (processed % (CHUNK_SIZE * UPDATE_UI_FREQUENCY) === 0) {
            const progress = Math.round((processed / totalFeatures) * 100);
            if (progressText) {
                progressText.textContent = `Processing ${layerType}s... ${progress}%`;
            }
            await new Promise(resolve => setTimeout(resolve, PROCESS_DELAY));
        }
    }

    return layerGroup;
}

const activeLayerTypes = {
    river: true,
    stream: false,
    canal: false,
    drain: false,
    other: false,
    buildings: true,
    transportation: false,
    landuse: false,
    inundation: false
};

const processedLayersByFile = new Map();
const activePanels = new Set();

async function processWaterwayData(features, progressText) {
    progressText.textContent = 'Processing waterways...';
    
    try {
        // Store all features by type
        const waterTypes = ['river', 'stream', 'canal', 'drain', 'other'];
        waterTypes.forEach(type => {
            const typeFeatures = features.features.filter(f => 
                f && f.properties && (f.properties.waterway || 'other') === type
            );
            
            if (typeFeatures.length > 0) {
                console.log(`Found ${typeFeatures.length} ${type} features`);
                layerFeatures[type] = typeFeatures;
            }
        });

        // Process rivers immediately if not already processed
        if (layerFeatures.river) {
            const riverLayer = await processFeatures(
                layerFeatures.river, 
                'river', 
                progressText
            );
            waterwayLayers.river.clearLayers();
            waterwayLayers.river.addLayer(riverLayer);
            waterwayLayers.river.addTo(map);

            // Store processed river layer
            processedLayersByFile.set(`${features.fileName}-river`, riverLayer);

            // Fit map to river features
            const bounds = waterwayLayers.river.getBounds();
            if (bounds.isValid()) {
                map.fitBounds(bounds, { padding: [50, 50] });
            }
        }

    } catch (error) {
        console.error('Error in processWaterwayData:', error);
        throw error;
    }
}

let updateTimeout;

// Update the OPENAI_CONFIG constant
const OPENAI_CONFIG = {
    apiKey: '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',
    model: 'gpt-4',
    endpoint: 'https://api.openai.com/v1/chat/completions',
    rateLimit: API_RATE_LIMIT
};

const ANALYSIS_RADIUS = 2000; // 2km radius for analysis

// Add these helper functions before the click handler

// Function to get weather forecast
async function getWeatherForecast(point) {
    try {
        const response = await fetch(`https://api.weatherapi.com/v1/forecast.json?key=${weatherConfig.apiKey}&q=${point.lat},${point.lng}&days=${weatherConfig.forecastDays}`);
        if (!response.ok) {
            throw new Error('Weather API error');
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching weather:', error);
        return {
            current: {
                temp_c: 20,
                precip_mm: 0,
                humidity: 50,
                condition: { text: 'Unknown' }
            },
            forecast: {
                forecastday: Array(7).fill({
                    date: new Date().toISOString().split('T')[0],
                    day: {
                        totalprecip_mm: 0,
                        avgtemp_c: 20
                    }
                })
            }
        };
    }
}

// Function to get elevation data
async function getElevationData(point) {
    try {
        // Use a fixed zoom level for elevation data
        const zoom = 12; // Fixed zoom level for consistent elevation data
        const lat = point.lat;
        const lng = point.lng;
        
        // Calculate tile coordinates
        const n = Math.pow(2, zoom);
        const xtile = Math.floor(n * ((lng + 180) / 360));
        const ytile = Math.floor(n * (1 - Math.log(Math.tan(lat * Math.PI / 180) + 1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2);

        const url = `https://api.maptiler.com/tiles/terrain-rgb/${zoom}/${xtile}/${ytile}.png?key=mcUdBlpX6o8IFQ03OMfE`;
        
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error('Elevation API error');
        }
        const blob = await response.blob();
        const bitmap = await createImageBitmap(blob);
        
        // Create a canvas to read pixel data
        const canvas = document.createElement('canvas');
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(bitmap, 0, 0);
        
        // Get the pixel data from the center of the tile
        const pixel = ctx.getImageData(bitmap.width/2, bitmap.height/2, 1, 1).data;
        const [r, g, b] = pixel;
        
        // Calculate elevation using Mapbox's terrain-RGB formula
        const elevation = -10000 + ((r * 256 * 256 + g * 256 + b) * 0.1);
        
        return elevation;
    } catch (error) {
        console.error('Error fetching elevation:', error);
        return 100; // Default elevation
    }
}

// Function to find nearby waterways
function findNearbyWaterways(point, radius) {
    const nearbyWaterways = [];
    const bounds = L.latLngBounds(
        L.latLng(point.lat - radius/111000, point.lng - radius/(111000 * Math.cos(point.lat * Math.PI/180))),
        L.latLng(point.lat + radius/111000, point.lng + radius/(111000 * Math.cos(point.lat * Math.PI/180)))
    );

    // Check each waterway layer
    Object.entries(waterwayLayers).forEach(([type, layer]) => {
        // Get features from layerFeatures (raw data)
        const features = layerFeatures[type];
        if (features) {
            const nearbyFeatures = features.filter(feature => {
                if (!feature.geometry || !feature.geometry.coordinates) return false;
                
                // Handle both single coordinates and coordinate arrays
                const coords = feature.geometry.coordinates;
                if (Array.isArray(coords[0])) {
                    // Line or polygon
                    return coords.some(coord => 
                        bounds.contains(L.latLng(coord[1], coord[0]))
                    );
                } else {
                    // Single point
                    return bounds.contains(L.latLng(coords[1], coords[0]));
                }
            });
            
            if (nearbyFeatures.length > 0) {
                console.log(`Found ${nearbyFeatures.length} nearby ${type} features`);
                nearbyWaterways.push(...nearbyFeatures);
            }
        }
    });

    console.log('Total nearby waterways:', nearbyWaterways.length);
    console.log('Nearby waterway details:', nearbyWaterways.map(w => ({
        type: w.properties.waterway,
        name: w.properties.name || 'unnamed',
        distance: calculateDistance(point, {
            lat: w.geometry.coordinates[0][1],
            lng: w.geometry.coordinates[0][0]
        })
    })));

    return nearbyWaterways;
}

// Function to calculate distance between points
function calculateDistance(point1, point2) {
    const R = 6371e3; // Earth's radius in meters
    const φ1 = point1.lat * Math.PI/180;
    const φ2 = point2.lat * Math.PI/180;
    const Δφ = (point2.lat - point1.lat) * Math.PI/180;
    const Δλ = (point2.lng - point1.lng) * Math.PI/180;

    const a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
            Math.cos(φ1) * Math.cos(φ2) *
            Math.sin(Δλ/2) * Math.sin(Δλ/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));

    return R * c; // Distance in meters
}

// Function to format elevation for display
function formatElevation(elevation) {
    return `${Math.round(elevation)}m above sea level`;
}

// Add the click handler for risk analysis
map.on('click', async function(e) {
    try {
        // Clear previous analysis
        riskOverlayLayer.clearLayers();

        // Show loading indicator
        const loadingDiv = L.DomUtil.create('div', 'loading-indicator');
        loadingDiv.innerHTML = 'Analyzing flood risk...';
        document.body.appendChild(loadingDiv);

        const point = {
            lat: e.latlng.lat,
            lng: e.latlng.lng
        };

        // Gather all required data
        const [weather, elevation, nearbyWaterways] = await Promise.all([
            getWeatherForecast(point),
            getElevationData(point),
            findNearbyWaterways(point, ANALYSIS_RADIUS)
        ]);

        // Get flooding data for the clicked location
        const floodingData = {};
        const radius = ANALYSIS_RADIUS;
        const clickBounds = L.latLngBounds(
            L.latLng(point.lat - radius/111000, point.lng - radius/(111000 * Math.cos(point.lat * Math.PI/180))),
            L.latLng(point.lat + radius/111000, point.lng + radius/(111000 * Math.cos(point.lat * Math.PI/180)))
        );

        // Check each flooding layer type
        ['buildings', 'transportation', 'landuse', 'inundation'].forEach(type => {
            if (layerFeatures[type]) {
                const features = layerFeatures[type].filter(feature => {
                    if (!feature.geometry || !feature.geometry.coordinates) return false;
                    
                    const coords = feature.geometry.coordinates;
                    try {
                        // Handle different geometry types
                        if (feature.geometry.type === 'Point') {
                            return clickBounds.contains(L.latLng(coords[1], coords[0]));
                        } else if (feature.geometry.type === 'LineString') {
                            return coords.some(coord => clickBounds.contains(L.latLng(coord[1], coord[0])));
                        } else if (feature.geometry.type === 'Polygon') {
                            // Check if any point of the polygon is within bounds
                            return coords[0].some(coord => clickBounds.contains(L.latLng(coord[1], coord[0])));
                        } else if (feature.geometry.type === 'MultiPolygon') {
                            // Check each polygon
                            return coords.some(polygon => 
                                polygon[0].some(coord => clickBounds.contains(L.latLng(coord[1], coord[0])))
                            );
                        }
                        return false;
                    } catch (error) {
                        console.warn('Error checking coordinates for feature:', feature);
                        return false;
                    }
                });

                if (features.length > 0) {
                    floodingData[type] = {
                        count: features.length,
                        features: features.map(f => {
                            try {
                                let distance;
                                if (f.geometry.type === 'Point') {
                                    distance = calculateDistance(point, {
                                        lat: f.geometry.coordinates[1],
                                        lng: f.geometry.coordinates[0]
                                    });
                                } else if (f.geometry.type === 'LineString') {
                                    // Use first point for distance
                                    distance = calculateDistance(point, {
                                        lat: f.geometry.coordinates[0][1],
                                        lng: f.geometry.coordinates[0][0]
                                    });
                                } else if (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon') {
                                    // Use first point of first ring for distance
                                    const coords = f.geometry.type === 'Polygon' ? 
                                        f.geometry.coordinates[0][0] : 
                                        f.geometry.coordinates[0][0][0];
                                    distance = calculateDistance(point, {
                                        lat: coords[1],
                                        lng: coords[0]
                                    });
                                }
                                
                                return {
                                    type: f.properties.type || type,
                                    distance: distance,
                                    properties: f.properties
                                };
                            } catch (error) {
                                console.warn('Error calculating distance for feature:', f);
                                return {
                                    type: f.properties.type || type,
                                    distance: null,
                                    properties: f.properties
                                };
                            }
                        })
                    };
                }
            }
        });

        // Format data for OpenAI with flooding data
        const analysisData = {
            location: {
                latitude: point.lat,
                longitude: point.lng,
                elevation: {
                    value: elevation,
                    unit: 'meters'
                }
            },
            weather: {
                current: {
                    temperature: weather.current.temp_c,
                    precipitation: weather.current.precip_mm,
                    humidity: weather.current.humidity,
                    condition: weather.current.condition.text,
                    wind_speed: weather.current.wind_kph,
                    pressure: weather.current.pressure_mb
                },
                forecast: weather.forecast.forecastday.map(day => ({
                    date: day.date,
                    precipitation_mm: day.day.totalprecip_mm,
                    avg_temp_c: day.day.avgtemp_c,
                    max_wind_kph: day.day.maxwind_kph,
                    chance_of_rain: day.day.daily_chance_of_rain
                }))
            },
            waterways: nearbyWaterways.map(waterway => ({
                type: waterway.properties.waterway,
                name: waterway.properties.name || 'unnamed',
                distance: calculateDistance(point, {
                    lat: waterway.geometry.coordinates[0][1],
                    lng: waterway.geometry.coordinates[0][0]
                }),
                properties: {
                    width: waterway.properties.width,
                    depth: waterway.properties.depth,
                    water_level: waterway.properties.water_level,
                    seasonal: waterway.properties.seasonal,
                    ...waterway.properties
                }
            })),
            flooding_data: {
                buildings_in_area: floodingData.buildings?.count || 0,
                transportation_features: floodingData.transportation?.count || 0,
                landuse_areas: floodingData.landuse?.count || 0,
                known_inundation_areas: floodingData.inundation?.count || 0,
                details: {
                    buildings: floodingData.buildings?.features || [],
                    transportation: floodingData.transportation?.features || [],
                    landuse: floodingData.landuse?.features || [],
                    inundation: floodingData.inundation?.features || []
                }
            },
            analysis_radius: ANALYSIS_RADIUS,
            terrain: {
                elevation: elevation,
                elevation_relative_to_waterways: nearbyWaterways.length > 0 ? 
                    Math.min(...nearbyWaterways.map(w => elevation - (w.properties.ele || 0))) :
                    null,
                waterway_count: nearbyWaterways.length,
                waterway_types: [...new Set(nearbyWaterways.map(w => w.properties.waterway))],
                closest_waterway_distance: nearbyWaterways.length > 0 ?
                    Math.min(...nearbyWaterways.map(w => calculateDistance(point, {
                        lat: w.geometry.coordinates[0][1],
                        lng: w.geometry.coordinates[0][0]
                    }))) : null
            }
        };

        console.log('Sending analysis data to OpenAI:', analysisData);

        // Get AI analysis
        const aiAnalysis = await analyzeWithOpenAI(analysisData);

        // Create analysis circle
        const riskCircle = L.circle([point.lat, point.lng], {
            radius: ANALYSIS_RADIUS,
            ...floodRiskStyles[aiAnalysis.riskLevel.toLowerCase()],
            fillOpacity: 0.3
        }).addTo(map);

        // Create enhanced popup content
        const popupContent = `
            <div class="flood-risk-popup">
                <h3>AI Flood Risk Assessment</h3>
                <div class="risk-level-indicator ${aiAnalysis.riskLevel.toLowerCase()}">
                    <p>Risk Level: <strong>${aiAnalysis.riskLevel}</strong></p>
                    <p>Risk Score: ${Math.round(aiAnalysis.riskScore * 100)}%</p>
                </div>
                
                <div class="risk-details">
                    <h4>Main Risk Factors</h4>
                    <ul>
                        ${aiAnalysis.mainFactors.map(factor => `<li>${factor}</li>`).join('')}
                    </ul>

                    <h4>Specific Concerns</h4>
                    <ul>
                        ${aiAnalysis.concerns.map(concern => `<li>${concern}</li>`).join('')}
                    </ul>

                    <h4>Recommendations</h4>
                    <ul>
                        ${aiAnalysis.recommendations.map(rec => `<li>${rec}</li>`).join('')}
                    </ul>

                    <div class="analysis-explanation">
                        <h4>Detailed Analysis</h4>
                        <p>${aiAnalysis.explanation}</p>
                    </div>

                    <div class="data-summary">
                        <h4>Data Summary</h4>
                        <p>Elevation: ${formatElevation(elevation)}</p>
                        <p>Nearby Waterways: ${nearbyWaterways.length}</p>
                        <p>Current Weather: ${weather.current.temp_c}°C, ${weather.current.condition.text}</p>
                    </div>
                </div>
            </div>
        `;

        riskCircle.bindPopup(popupContent, {
            maxWidth: 400,
            maxHeight: 500,
            autoPan: true,
            className: 'flood-risk-popup'
        }).openPopup();

    } catch (error) {
        console.error('Error analyzing flood risk:', error);
        alert('Unable to analyze flood risk at this location');
    } finally {
        // Remove loading indicator
        const loadingDiv = document.querySelector('.loading-indicator');
        if (loadingDiv) {
            loadingDiv.remove();
        }
    }
});

// Add helper functions
async function analyzeWithOpenAI(data) {
    const messages = [
        {
            role: "system",
            content: `You are a flood risk analysis expert. Analyze the provided data including:
                - Weather conditions and forecasts
                - Terrain elevation and nearby waterways
                - Existing buildings and infrastructure
                - Known flood-prone areas and inundation zones
                - Land use patterns
                Provide a comprehensive flood risk assessment considering all these factors.
                Always respond with a valid JSON object containing:
                - riskLevel (LOW/MEDIUM/HIGH)
                - riskScore (0-1)
                - mainFactors (array of key risk factors)
                - concerns (array of specific concerns)
                - recommendations (array of actionable recommendations)
                - explanation (detailed analysis string)`
        },
        {
            role: "user",
            content: JSON.stringify(data)
        }
    ];

    try {
        // Check rate limit
        const now = Date.now();
        const timeSinceLastRequest = now - API_RATE_LIMIT.lastRequestTime;
        const minTimeBetweenRequests = (60 * 1000) / API_RATE_LIMIT.requestsPerMinute;

        if (timeSinceLastRequest < minTimeBetweenRequests) {
            const waitTime = minTimeBetweenRequests - timeSinceLastRequest;
            console.log(`Rate limiting: waiting ${Math.round(waitTime/1000)} seconds...`);
            await new Promise(resolve => setTimeout(resolve, waitTime));
        }

        API_RATE_LIMIT.lastRequestTime = Date.now();

        const response = await fetch(OPENAI_CONFIG.endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${OPENAI_CONFIG.apiKey}`
            },
            body: JSON.stringify({
                model: OPENAI_CONFIG.model,
                messages: messages,
                temperature: 0.7,
                max_tokens: 1000
            })
        });

        if (!response.ok) {
            if (response.status === 429) {
                console.warn('Rate limit exceeded, using local analysis');
                return generateLocalAnalysis(data);
            }
            throw new Error(`OpenAI API error: ${response.status}`);
        }

        const result = await response.json();
        const content = result.choices[0].message.content;
        return JSON.parse(content);

    } catch (error) {
        console.error('Error in OpenAI analysis:', error);
        return generateLocalAnalysis(data);
    }
}

// Add a function for local analysis when API is unavailable
function generateLocalAnalysis(data) {
    // Simple risk scoring based on available data
    let riskScore = 0;
    const factors = [];
    const concerns = [];
    const recommendations = [];

    // Check waterways
    if (data.waterways.length > 0) {
        const closestWaterway = Math.min(...data.waterways.map(w => w.distance));
        if (closestWaterway < 500) {
            riskScore += 0.3;
            factors.push('Close proximity to waterway');
            concerns.push(`Waterway within ${Math.round(closestWaterway)}m`);
        }
    }

    // Check elevation relative to waterways
    if (data.terrain.elevation_relative_to_waterways !== null) {
        if (data.terrain.elevation_relative_to_waterways < 5) {
            riskScore += 0.2;
            factors.push('Low elevation relative to waterways');
            concerns.push('Area is at low elevation compared to nearby waterways');
        }
    }

    // Check weather
    if (data.weather.current.precipitation > 0) {
        riskScore += 0.1;
        factors.push('Current precipitation');
    }
    
    // Check flooding data
    if (data.flooding_data.known_inundation_areas > 0) {
        riskScore += 0.3;
        factors.push('Known inundation area');
        concerns.push('Location is in a known flood-prone area');
    }

    // Add basic recommendations
    recommendations.push('Monitor local weather conditions');
    recommendations.push('Stay alert for flood warnings');
    if (riskScore > 0.5) {
        recommendations.push('Consider flood protection measures');
    }

    // Determine risk level
    let riskLevel = 'LOW';
    if (riskScore > 0.7) riskLevel = 'HIGH';
    else if (riskScore > 0.3) riskLevel = 'MEDIUM';

    return {
        riskLevel,
        riskScore: Math.min(1, riskScore),
        mainFactors: factors,
        concerns,
        recommendations,
        explanation: `Local analysis based on ${factors.length} main factors. This is a fallback analysis due to API limitations.`
    };
}

// Add this near the top with other layer definitions
const riskOverlayLayer = L.featureGroup().addTo(map);

// Add this function near other helper functions
function createPopupContent(properties) {
    if (!properties) return 'No information available';
    
    const excludedFields = ['Shape_Leng', 'Shape_Area', 'OBJECTID', 'FID'];
    
    return Object.entries(properties)
        .filter(([key, value]) => {
            // Filter out null/empty values and excluded fields
            return value !== null && 
                   value !== '' && 
                   !excludedFields.includes(key) &&
                   typeof value !== 'undefined';
        })
        .map(([key, value]) => {
            // Format the key for display
            const formattedKey = key
                .split('_')
                .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
                .join(' ');
            
            // Format the value
            let formattedValue = value;
            if (typeof value === 'number') {
                formattedValue = value.toLocaleString();
            } else if (typeof value === 'boolean') {
                formattedValue = value ? 'Yes' : 'No';
            }
            
            return `<strong>${formattedKey}:</strong> ${formattedValue}`;
        })
        .join('<br>');
}
