// API Keys and Configuration
export const CONFIG = {
    // MapTiler API configuration
    mapTiler: {
        apiKey: 'mcUdBlpX6o8IFQ03OMfE',
        terrainEndpoint: 'https://api.maptiler.com/tiles/terrain-rgb'
    },

    // Weather API configuration
    weather: {
        apiKey: '4e203ee12a8247af85f122549240612',
        endpoint: 'https://api.weatherapi.com/v1',
        forecastDays: 7,
        updateInterval: 3600000 // 1 hour
    },

    // OpenAI API configuration
    openAI: {
        apiKey: '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',
        model: 'gpt-4',
        endpoint: 'https://api.openai.com/v1/chat/completions'
    },

    // Map configuration
    map: {
        defaultView: {
            center: [45.9432, 24.9668], // Romania
            zoom: 7
        },
        maxZoom: 18,
        minZoom: 5
    },

    // Analysis configuration
    analysis: {
        radius: 2000, // meters
        gridCellSize: 200, // meters
        maxFeatures: 5000
    },

    // Flood risk thresholds
    floodRisk: {
        elevationThreshold: 5, // meters above nearest waterway
        rainfallThreshold: 50, // mm per day
        soilSaturationThreshold: 0.8, // 0-1 scale
        waterLevelThreshold: 2 // meters above normal
    }
}; 