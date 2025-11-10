import os
import json

CONFIG_FILE = "config.json"

def get_config():
    """Charge la configuration depuis le fichier JSON"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {
        "OPENAI_API_KEY": "",
        "EMAIL_ADDRESS": "",
        "EMAIL_PASSWORD": ""
    }

def save_config(openai_key, email_address, email_password):
    """Sauvegarde la configuration dans le fichier JSON"""
    config = {
        "OPENAI_API_KEY": openai_key,
        "EMAIL_ADDRESS": email_address,
        "EMAIL_PASSWORD": email_password
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
    return True

def is_configured():
    """Vérifie si toutes les clés sont configurées"""
    config = get_config()
    return all([
        config.get("OPENAI_API_KEY"),
        config.get("EMAIL_ADDRESS"),
        config.get("EMAIL_PASSWORD")
    ])

