
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

TWILIO_ACCOUNT_SID = "AC96a0ede1752a69124f025f420594b0b8"
TWILIO_AUTH_TOKEN = "d178fd017ccc327cb43a23e5e60a88d4"
TWILIO_PHONE_NUMBER = "whatsapp:+14155238886"  # Format: whatsapp:+1234567890
WHATSAPP_GROUP_ID = "+40749884014"
