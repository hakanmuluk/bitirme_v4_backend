# db.py
from os import getenv
from dotenv import load_dotenv
from pymongo import MongoClient

# this will read the .env file and set os.environ["MONGODB_URI"]
load_dotenv()

# grab it out of the environment
mongo_uri = getenv("MONGODB_URI")
if not mongo_uri:
    raise RuntimeError("MONGODB_URI env var not set")

# create your client with the secret kept out of source
mongo_client = MongoClient(mongo_uri)
db = mongo_client["chatbot_db"]
users_collection = db["users"]
notifications_collection = db["notifications"]
tree_collection = db["tree"]   
stats_collection = db["stats"]