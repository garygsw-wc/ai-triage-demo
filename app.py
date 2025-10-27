import streamlit as st
import requests
import json
import uuid
from datetime import datetime, timedelta
import pytz
import re
import random
import hashlib

# Page configuration - optimized for mobile
st.set_page_config(
    page_title="AI Triage Demo",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="collapsed"  # Collapsed by default for mobile
)

# Mobile-friendly CSS
st.markdown("""
<style>
    /* Mobile-first responsive design */
    @media (max-width: 768px) {
        /* Reduce padding on mobile */
        .main .block-container {
            padding-top: 1rem;
            padding-left: 1rem;
            padding-right: 1rem;
            padding-bottom: 1rem;
            max-width: 100%;
        }
        
        /* Make sidebar collapsible and overlay on mobile */
        section[data-testid="stSidebar"] {
            width: 80% !important;
            max-width: 300px;
        }
        
        /* Adjust text sizes for mobile */
        h1 {
            font-size: 1.75rem !important;
        }
        
        h2 {
            font-size: 1.5rem !important;
        }
        
        h3 {
            font-size: 1.25rem !important;
        }
        
        /* Make buttons larger and easier to tap */
        .stButton > button {
            width: 100%;
            padding: 0.75rem 1rem !important;
            font-size: 1rem !important;
            margin-bottom: 0.5rem;
        }
        
        /* Improve text input on mobile */
        .stTextInput > div > div > input,
        .stTextArea > div > div > textarea {
            font-size: 16px !important; /* Prevents zoom on iOS */
            padding: 0.75rem !important;
        }
        
        /* Adjust chat messages */
        .stChatMessage {
            padding: 0.75rem !important;
            margin-bottom: 0.5rem !important;
        }
        
        /* Make expanders more touch-friendly */
        .streamlit-expanderHeader {
            padding: 0.75rem !important;
            font-size: 1rem !important;
        }
        
        /* Adjust columns to stack on mobile */
        .row-widget.stHorizontal {
            flex-direction: column !important;
        }
        
        /* Better spacing for mobile */
        .element-container {
            margin-bottom: 0.5rem;
        }
        
        /* Stack columns vertically on mobile */
        [data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
        }
    }
    
    /* General improvements for all screen sizes */
    .stChatMessage {
        border-radius: 10px;
    }
    
    /* Improve conversation list appearance */
    .conversation-item {
        padding: 0.75rem;
        margin-bottom: 0.5rem;
        border-radius: 8px;
        cursor: pointer;
        transition: background-color 0.2s;
    }
    
    /* Better touch targets for mobile */
    @media (max-width: 768px) {
        .stSelectbox, .stNumberInput, .stSlider {
            margin-bottom: 1rem;
        }
        
        /* Larger radio buttons */
        .stRadio > div {
            padding: 0.5rem 0;
        }
    }
    
    /* Improve assessment state display */
    .assessment-section {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 0.75rem;
    }
    
    @media (max-width: 768px) {
        .assessment-section {
            padding: 0.75rem;
        }
    }
</style>
""", unsafe_allow_html=True)

# Timezone configuration (UTC+8)
LOCAL_TZ = pytz.timezone('Asia/Singapore')  # UTC+8

# Custom JSON encoder for datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

# Storage functions using query params for auth persistence
def save_auth_to_storage(email: str, auth_token: str):
    """Save authentication to URL query params (persists across refreshes)"""
    import base64
    auth_data = {
        'email': email,
        'token': auth_token,
        'timestamp': datetime.now(LOCAL_TZ).isoformat()
    }
    # Encode to base64
    auth_json = json.dumps(auth_data)
    auth_b64 = base64.b64encode(auth_json.encode()).decode()
    
    # Save to query params
    try:
        st.query_params["auth"] = auth_b64
    except:
        pass

def load_auth_from_storage():
    """Load authentication from URL query params"""
    import base64
    try:
        if "auth" in st.query_params:
            auth_b64 = st.query_params["auth"]
            auth_json = base64.b64decode(auth_b64).decode()
            auth_data = json.loads(auth_json)
            return auth_data
    except Exception as e:
        print(f"Error loading auth: {e}")
        pass
    return None

def clear_auth_from_storage():
    """Clear authentication from storage"""
    try:
        if "auth" in st.query_params:
            del st.query_params["auth"]
    except:
        pass

def save_conversations_to_storage():
    """Save conversations to session state and query params"""
    import base64
    try:
        # Serialize conversations
        conv_json = json.dumps(st.session_state.conversations, cls=DateTimeEncoder)
        conv_b64 = base64.b64encode(conv_json.encode()).decode()
        
        # Save to query params (this persists across refreshes)
        st.query_params["conv"] = conv_b64
    except Exception as e:
        print(f"Error saving conversations: {e}")

def load_conversations_from_storage():
    """Load conversations from query params"""
    import base64
    try:
        if "conv" in st.query_params:
            conv_b64 = st.query_params["conv"]
            conv_json = base64.b64decode(conv_b64).decode()
            conversations = json.loads(conv_json)
            
            # Parse datetime strings back to datetime objects
            return parse_datetime_in_dict(conversations)
    except Exception as e:
        print(f"Error loading conversations: {e}")
    return {}

def parse_datetime_in_dict(obj):
    """Recursively parse ISO datetime strings back to datetime objects"""
    if isinstance(obj, dict):
        return {k: parse_datetime_in_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [parse_datetime_in_dict(item) for item in obj]
    elif isinstance(obj, str):
        # Try to parse ISO datetime strings
        try:
            # Check if it looks like an ISO datetime
            if 'T' in obj and ('-' in obj or ':' in obj):
                dt = datetime.fromisoformat(obj.replace('Z', '+00:00'))
                return dt
        except:
            pass
    return obj

def init_session_state():
    """Initialize session state variables"""
    if 'conversations' not in st.session_state:
        # Try to load from storage first
        stored_conversations = load_conversations_from_storage()
        st.session_state.conversations = stored_conversations if stored_conversations else {}
    
    # Migrate existing conversations to add missing fields
    migrate_conversations()
    
    if 'current_conversation_id' not in st.session_state:
        st.session_state.current_conversation_id = None
    
    if 'patient_info' not in st.session_state:
        st.session_state.patient_info = {"age": 35, "gender": "Male"}
    
    if 'assessment_state' not in st.session_state:
        st.session_state.assessment_state = {}
    
    if 'otp_sent' not in st.session_state:
        st.session_state.otp_sent = False
    
    if 'otp_code' not in st.session_state:
        st.session_state.otp_code = None
    
    if 'otp_email' not in st.session_state:
        st.session_state.otp_email = None
    
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    
    if 'user_email' not in st.session_state:
        st.session_state.user_email = None
    
    # Auto-create first conversation if none exist
    if not st.session_state.conversations:
        create_new_conversation()

def migrate_conversations():
    """Migrate existing conversations to add missing fields"""
    now = datetime.now(LOCAL_TZ)
    needs_save = False
    
    for conv_id, conv in st.session_state.conversations.items():
        # Add missing created_at
        if 'created_at' not in conv:
            conv['created_at'] = now
            needs_save = True
        
        # Add missing updated_at
        if 'updated_at' not in conv:
            conv['updated_at'] = conv.get('created_at', now)
            needs_save = True
        
        # Add missing title
        if 'title' not in conv:
            conv['title'] = f"Conversation {conv_id[:8]}"
            needs_save = True
        
        # Add missing messages
        if 'messages' not in conv:
            conv['messages'] = []
            needs_save = True
        
        # Add missing assessment_state
        if 'assessment_state' not in conv:
            conv['assessment_state'] = {}
            needs_save = True
        
        # Add missing session_id
        if 'session_id' not in conv:
            conv['session_id'] = str(uuid.uuid4())
            needs_save = True
        
        # Add missing state (for API compatibility)
        if 'state' not in conv:
            conv['state'] = conv.get('assessment_state', {})
            needs_save = True
        
        # Add missing summary
        if 'summary' not in conv:
            conv['summary'] = ""
            needs_save = True
    
    # Save if we made any changes
    if needs_save:
        save_conversations_to_storage()


def generate_auth_token(email: str) -> str:
    """Generate a secure auth token"""
    timestamp = datetime.now(LOCAL_TZ).isoformat()
    token_string = f"{email}:{timestamp}:{st.secrets.get('SECRET_KEY', 'default-secret')}"
    return hashlib.sha256(token_string.encode()).hexdigest()

# Google Sign-In functionality
def get_redirect_uri():
    """Get the appropriate redirect URI based on environment"""
    try:
        # Check if we have a custom redirect URI in secrets
        if "redirect_uri" in st.secrets:
            return st.secrets["redirect_uri"]
    except:
        pass
    
    # Auto-detect based on current URL
    try:
        # Try to get the current host from Streamlit
        import streamlit.web.bootstrap as bootstrap
        from streamlit import runtime
        
        # Check if running locally
        if runtime.exists():
            # Get the browser's current URL if available
            # For local development, default to localhost
            return "http://localhost:8501/"
    except:
        pass
    
    # Default fallback
    return "http://localhost:8501/"

def get_google_oauth_url():
    """Generate Google OAuth URL for authentication"""
    try:
        from urllib.parse import urlencode
        
        client_id = st.secrets["google_client_id"]
        redirect_uri = get_redirect_uri()
        
        # Google OAuth endpoint
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent"
        }
        
        return f"{auth_url}?{urlencode(params)}"
    except Exception as e:
        return None

def exchange_code_for_token(code: str):
    """Exchange authorization code for user info"""
    try:
        import requests
        
        client_id = st.secrets["google_client_id"]
        client_secret = st.secrets["google_client_secret"]
        redirect_uri = get_redirect_uri()
        
        # Exchange code for token
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }
        
        token_response = requests.post(token_url, data=token_data)
        token_json = token_response.json()
        
        if "access_token" in token_json:
            # Get user info
            access_token = token_json["access_token"]
            userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
            headers = {"Authorization": f"Bearer {access_token}"}
            
            user_response = requests.get(userinfo_url, headers=headers)
            user_info = user_response.json()
            
            return user_info
        
        return None
    except Exception as e:
        st.error(f"Error exchanging code: {e}")
        return None

def render_google_signin_button():
    """Render Google Sign-In button with instructions"""
    
    # Check if we have an authorization code in the URL
    if "code" in st.query_params:
        code = st.query_params["code"]
        
        # Exchange code for user info
        user_info = exchange_code_for_token(code)
        
        if user_info and "email" in user_info:
            email = user_info["email"]
            
            # Check if email is authorized
            authorized_emails = st.secrets.get("AUTHORIZED_EMAILS", "").split(",")
            if is_email_authorized(email, authorized_emails):
                # Generate auth token
                auth_token = generate_auth_token(email)
                
                # Save to storage
                save_auth_to_storage(email, auth_token)
                
                # Set session state
                st.session_state.authenticated = True
                st.session_state.user_email = email
                
                # Clear the code from URL
                del st.query_params["code"]
                
                st.success("✅ Login successful!")
                st.rerun()
            else:
                st.error("❌ Unauthorized email address.")
                del st.query_params["code"]
        else:
            st.error("❌ Failed to get user information.")
            del st.query_params["code"]
    
    # Check for OAuth error
    if "error" in st.query_params:
        error = st.query_params.get("error", "unknown")
        if error == "redirect_uri_mismatch":
            st.error("❌ **Redirect URI Mismatch Error**")
            st.warning("The redirect URI in your Google Cloud Console doesn't match your app URL.")
            
            # Show current app URL
            try:
                import socket
                hostname = socket.gethostname()
                st.info(f"🔗 **Your current app URL might be:** `https://{hostname}/`")
            except:
                pass
            
            with st.expander("🔧 How to Fix This Error", expanded=True):
                st.markdown("""
                ### Steps to Fix Redirect URI Mismatch:
                
                1. **Find your app's exact URL:**
                   - Look at your browser's address bar
                   - Copy the full URL (e.g., `https://your-app.streamlit.app/`)
                   - Make sure to include the trailing slash `/`
                
                2. **Update Google Cloud Console:**
                   - Go to [Google Cloud Console](https://console.cloud.google.com/)
                   - Navigate to: **APIs & Services** → **Credentials**
                   - Click on your OAuth 2.0 Client ID
                   - Under "Authorized redirect URIs", click **ADD URI**
                   - Paste your exact app URL: `https://your-app.streamlit.app/`
                   - Click **SAVE**
                
                3. **Update your secrets.toml:**
                   ```toml
                   [google_oauth]
                   client_id = "your-client-id.apps.googleusercontent.com"
                   client_secret = "your-client-secret"
                   redirect_uri = "https://your-app.streamlit.app/"
                   ```
                   Make sure the `redirect_uri` matches EXACTLY what you added in Google Cloud Console.
                
                4. **Common mistakes:**
                   - ❌ `http://` instead of `https://`
                   - ❌ Missing trailing slash: `https://app.com` vs `https://app.com/`
                   - ❌ Using `localhost` in production
                   - ❌ Wrong subdomain or path
                
                5. **After fixing, click the Sign in button again!**
                """)
            
            # Clear error from URL
            del st.query_params["error"]
        else:
            st.error(f"❌ OAuth Error: {error}")
            del st.query_params["error"]
    
    # Check if Google OAuth is configured
    try:
        oauth_url = get_google_oauth_url()
        
        if oauth_url:
            # Show the current redirect URI being used
            redirect_uri = get_redirect_uri()
            
            # Detect if running locally
            is_local = "localhost" in redirect_uri or "127.0.0.1" in redirect_uri
            
            if is_local:
                st.info("🏠 **Running in Local Development Mode**")
            
            # Create a styled button that links to Google OAuth
            st.markdown("""
                <style>
                .google-btn {
                    display: inline-flex;
                    align-items: center;
                    gap: 12px;
                    background: white;
                    color: #3c4043;
                    border: 1px solid #dadce0;
                    border-radius: 4px;
                    padding: 12px 24px;
                    font-size: 14px;
                    font-weight: 500;
                    text-decoration: none;
                    transition: background-color 0.2s, box-shadow 0.2s;
                    cursor: pointer;
                }
                .google-btn:hover {
                    background: #f8f9fa;
                    box-shadow: 0 1px 2px 0 rgba(60,64,67,.3), 0 1px 3px 1px rgba(60,64,67,.15);
                }
                .google-icon {
                    width: 18px;
                    height: 18px;
                }
                </style>
            """, unsafe_allow_html=True)
            
            # Display Google Sign-In button
            st.markdown(f"""
                <a href="{oauth_url}" class="google-btn" target="_self">
                    <svg class="google-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                        <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                        <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                        <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                    </svg>
                    Sign in with Google
                </a>
            """, unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
        else:
            raise Exception("OAuth URL not configured")
            
    except Exception as e:
        st.info("📝 **Google OAuth Setup Required**")
        
        with st.expander("📖 How to set up Google Sign-In (click to expand)"):
            st.markdown("""
            ### Setup Instructions:
            
            1. **Create Google OAuth credentials:**
               - Go to [Google Cloud Console](https://console.cloud.google.com/)
               - Create a new project or select existing one
               - Go to "APIs & Services" → "Credentials"
               - Click "Create Credentials" → "OAuth 2.0 Client ID"
               - Choose "Web application"
               - Add **BOTH** redirect URIs:
                 - For local development: `http://localhost:8501/`
                 - For production: `https://your-app.streamlit.app/`
               - Copy the Client ID and Client Secret
            
            2. **For Local Development:**
               Create `.streamlit/secrets.toml` in your project:
               ```toml
               [google_oauth]
               client_id = "your-client-id.apps.googleusercontent.com"
               client_secret = "your-client-secret"
               # redirect_uri is auto-detected for localhost
               
               AUTHORIZED_EMAILS = "your-email@gmail.com"
               ```
            
            3. **For Production (Streamlit Cloud):**
               Add to your app's secrets:
               ```toml
               [google_oauth]
               client_id = "your-client-id.apps.googleusercontent.com"
               client_secret = "your-client-secret"
               redirect_uri = "https://your-app.streamlit.app/"
               
               AUTHORIZED_EMAILS = "your-email@gmail.com,@yourdomain.com"
               ```
            
            4. **Note:** Google OAuth is completely FREE for basic authentication!
            """)
        
        st.info("For now, you can use the simple email-based login below.")

# API configuration
API_BASE_URL = st.secrets.get("API_BASE_URL", "https://dbc-e469a72f-3a02.cloud.databricks.com/serving-endpoints/agents_gen_ai-ai_triage-ai_triage_langgraph_v4")
DATABRICKS_TOKEN = st.secrets.get("DATABRICKS_TOKEN", "your_token_here")

def call_api(user_message: str, session_id: str, generate_summary: bool = False) -> dict:
    """Call the AI agent API using Databricks serving endpoint format"""
    headers = {"Content-Type": "application/json"}
    auth = ("token", DATABRICKS_TOKEN)
    
    payload = {
        "messages": [{"role": "user", "content": user_message}],
        "custom_inputs": {
            "session_id": session_id,
            "gender": st.session_state.patient_info["gender"],
            "age": st.session_state.patient_info["age"],
            "user_email": st.session_state.get("user_email", "unknown@example.com")
        }
    }
    
    if generate_summary:
        payload["custom_inputs"]["generate_summary"] = True
    
    try:
        start_time = datetime.now(LOCAL_TZ)
        url = f"{API_BASE_URL}/invocations"
        response = requests.post(url, json=payload, headers=headers, auth=auth)
        response.raise_for_status()
        
        end_time = datetime.now(LOCAL_TZ)
        latency = (end_time - start_time).total_seconds()
        
        result = response.json()
        result["_latency"] = round(latency, 2)
        
        return result
    except Exception as e:
        st.error(f"API Error: {str(e)}")
        return None

def is_valid_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def is_email_authorized(email: str, authorized_list: list) -> bool:
    """Check if email or domain is authorized"""
    email = email.strip().lower()
    
    for authorized in authorized_list:
        authorized = authorized.strip().lower()
        
        # Check for exact email match
        if email == authorized:
            return True
        
        # Check for domain match (e.g., @company.com)
        if authorized.startswith('@'):
            email_domain = '@' + email.split('@')[1] if '@' in email else ''
            if email_domain == authorized:
                return True
    
    return False

def generate_otp() -> str:
    """Generate a 6-digit OTP"""
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])

def send_otp_email(email: str, otp: str):
    """Send OTP via email (demo mode - would integrate with email service in production)"""
    # In production, this would use SendGrid, AWS SES, or similar
    print(f"[DEMO MODE] Sending OTP {otp} to {email}")
    # For demo purposes, we just display it in the UI
    return True

def generate_auth_token(email: str) -> str:
    """Generate a secure auth token"""
    timestamp = datetime.now(LOCAL_TZ).isoformat()
    token_string = f"{email}:{timestamp}:{st.secrets.get('SECRET_KEY', 'default-secret')}"
    return hashlib.sha256(token_string.encode()).hexdigest()

def create_new_conversation():
    """Create a new conversation with initial template message"""
    conversation_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    initial_message = "Hi, I'm your AI Triage Chatbot. I'm here to discuss your symptoms and help guide you to the next appropriate care option. Could you please describe any symptoms you are experiencing?"
    
    now = datetime.now(LOCAL_TZ)
    
    st.session_state.conversations[conversation_id] = {
        'id': conversation_id,
        'session_id': session_id,
        'title': f"Conversation {len(st.session_state.conversations) + 1}",
        'messages': [{"role": "assistant", "content": initial_message, "timestamp": now, "latency": None}],
        'created_at': now,
        'updated_at': now,
        'state': {},
        'summary': "",
        'assessment_state': {}
    }
    
    st.session_state.current_conversation_id = conversation_id
    st.session_state.assessment_state = {}
    
    # Save to storage
    save_conversations_to_storage()
    
    return conversation_id

def get_current_conversation():
    """Get the current conversation"""
    if not st.session_state.current_conversation_id:
        return None
    return st.session_state.conversations.get(st.session_state.current_conversation_id)

def update_conversation_title(conversation_id: str, first_message: str):
    """Update conversation title based on first message"""
    if conversation_id in st.session_state.conversations:
        # Use first 50 characters of first message as title
        title = first_message[:50] + "..." if len(first_message) > 50 else first_message
        st.session_state.conversations[conversation_id]['title'] = title
        save_conversations_to_storage()

def delete_conversation(conversation_id: str):
    """Delete a conversation"""
    if conversation_id in st.session_state.conversations:
        del st.session_state.conversations[conversation_id]
        
        if st.session_state.current_conversation_id == conversation_id:
            st.session_state.current_conversation_id = None
            st.session_state.assessment_state = {}
        
        save_conversations_to_storage()

def process_response(response: dict, conversation_id: str, summary=False):
    """Process the API response and update conversation state"""
    if not response:
        st.warning("No response received from API")
        return
    
    conversation = st.session_state.conversations.get(conversation_id)
    if not conversation:
        st.error(f"Conversation {conversation_id} not found")
        return
    
    # Extract the assistant's message
    if "messages" in response and len(response["messages"]) > 0:
        assistant_message = response["messages"][0].get("content", "")
    else:
        assistant_message = "I apologize, but I couldn't process that response."
    
    latency = response.get("_latency", None)
    
    # Add assistant message with local timezone
    if not summary:
        conversation["messages"].append({
            "role": "assistant",
            "content": assistant_message,
            "timestamp": datetime.now(LOCAL_TZ),
            "latency": latency
        })
        
        # Extract assessment data from custom_outputs field
        if "custom_outputs" in response:
            assessment_data = response["custom_outputs"]
            conversation["state"] = assessment_data
            st.session_state.assessment_state = assessment_data
        else:
            st.warning("⚠️ DEBUG - No 'custom_outputs' field in API response")
    
        # Automatically generate summary when result is no longer pending
        result_status = (conversation["state"].get("result") or "").lower() if conversation["state"].get("result") is not None else "pending"
        if result_status and result_status != "pending" and not conversation.get("summary"):
            with st.spinner("Auto-generating summary..."):
                response = call_api("Generate summary for this conversation.", conversation["session_id"], generate_summary=True)
                if response:
                    conversation["summary"] = response["messages"][0].get("content", "")
    
        # Update conversation timestamp
        conversation['updated_at'] = datetime.now(LOCAL_TZ)
    else:
        conversation["summary"] = assistant_message
    
    save_conversations_to_storage()
    
    st.success("✅ Response processed successfully")

def render_mobile_sidebar():
    """Render mobile-friendly sidebar"""
    with st.sidebar:
        # Patient Info Section - Auto-updates on change
        with st.expander("👤 Patient Info", expanded=True):
            # Age slider with auto-update
            age = st.slider(
                "Age", 
                min_value=0, 
                max_value=120, 
                value=st.session_state.patient_info["age"]
            )
            
            # Gender selection with auto-update
            gender_options = ["Male", "Female", "Other"]
            current_gender_index = gender_options.index(st.session_state.patient_info["gender"]) if st.session_state.patient_info["gender"] in gender_options else 0
            gender = st.selectbox(
                "Gender", 
                gender_options,
                index=current_gender_index
            )
            
            # Auto-update patient info if values changed
            if age != st.session_state.patient_info["age"] or gender != st.session_state.patient_info["gender"]:
                st.session_state.patient_info = {"age": age, "gender": gender}
                st.success("✅ Patient info updated!")
        
        st.markdown("---")
        
        # Assessment Details Section - moved from main area
        render_sidebar_assessment()
                
        st.markdown("### 💬 Conversations")
        
        # New conversation button
        if st.button("➕ New Conversation", use_container_width=True, type="primary"):
            create_new_conversation()
            st.rerun()
        
        st.markdown("---")
        
        # List conversations (most recent first)
        # Fix: Handle missing updated_at field
        sorted_convs = sorted(
            st.session_state.conversations.values(),
            key=lambda x: x.get('updated_at', datetime.now(LOCAL_TZ)),
            reverse=True
        )
        
        for conv in sorted_convs:
            is_current = conv['id'] == st.session_state.current_conversation_id
            
            # Conversation item
            col1, col2 = st.columns([4, 1])
            
            with col1:
                button_type = "primary" if is_current else "secondary"
                if st.button(
                    conv.get('title', 'Untitled Conversation'),
                    key=f"conv_{conv['id']}",
                    use_container_width=True,
                    type=button_type
                ):
                    st.session_state.current_conversation_id = conv['id']
                    # Load assessment state for this conversation (use 'state' field which contains assessment data)
                    st.session_state.assessment_state = conv.get('state', conv.get('assessment_state', {}))
                    st.rerun()
            
            with col2:
                if st.button("🗑️", key=f"del_{conv['id']}", use_container_width=True):
                    delete_conversation(conv['id'])
                    st.rerun()
            
            # Show last updated time
            updated_time = conv.get('updated_at', conv.get('created_at'))
            if updated_time:
                if isinstance(updated_time, str):
                    try:
                        updated_time = datetime.fromisoformat(updated_time)
                    except:
                        pass
                
                if isinstance(updated_time, datetime):
                    time_str = updated_time.strftime("%b %d, %I:%M %p")
                    st.caption(f"📅 {time_str}")
            
            st.markdown("")

def render_custom_chat(conversation):
    """Render chat with custom CSS (original look and feel)"""
    chat_messages_html = ""
    
    for message in conversation.get("messages", []):
        # Format timestamp in local timezone
        if "timestamp" in message:
            if isinstance(message["timestamp"], str):
                # Parse ISO format string
                timestamp = datetime.fromisoformat(message["timestamp"])
            else:
                timestamp = message["timestamp"]
            
            # Ensure timezone aware
            if timestamp.tzinfo is None:
                timestamp = LOCAL_TZ.localize(timestamp)
            else:
                timestamp = timestamp.astimezone(LOCAL_TZ)
            
            timestamp_str = timestamp.strftime("%H:%M")
        else:
            timestamp_str = datetime.now(LOCAL_TZ).strftime("%H:%M")
        
        if message["role"] == "user":
            chat_messages_html += f"""
            <div class="message-container">
                <div class="user-message">
                    {message["content"]}
                </div>
                <div class="user-timestamp">
                    {timestamp_str}
                </div>
            </div>
            """
        else:
            latency_text = ""
            if "latency" in message and message["latency"] is not None:
                latency_text = f" • {message['latency']}s"
            
            chat_messages_html += f"""
            <div class="message-container">
                <div class="assistant-message">
                    {message["content"]}
                </div>
                <div class="assistant-timestamp">
                    {timestamp_str}{latency_text}
                </div>
            </div>
            """
    
    # Display chat with original custom CSS
    st.components.v1.html(f"""
    <style>
    .user-message {{
        background-color: #007BFF;
        color: white;
        padding: 10px 15px;
        border-radius: 18px;
        margin: 5px 0;
        margin-left: 20%;
        text-align: right;
        max-width: 70%;
        float: right;
        clear: both;
        margin-bottom: 2px;
    }}
    
    .assistant-message {{
        background-color: #F1F1F1;
        color: black;
        padding: 10px 15px;
        border-radius: 18px;
        margin: 5px 0;
        margin-right: 20%;
        max-width: 70%;
        float: left;
        clear: both;
        margin-bottom: 2px;
    }}
    
    .user-timestamp {{
        text-align: right;
        font-size: 10px;
        color: #666;
        margin-left: 20%;
        margin-bottom: 15px;
        clear: both;
    }}
    
    .assistant-timestamp {{
        text-align: left;
        font-size: 10px;
        color: #666;
        margin-right: 20%;
        margin-bottom: 15px;
        clear: both;
    }}
    
    .message-container {{
        display: block;
        width: 100%;
        margin-bottom: 10px;
    }}
    
    .message-container::after {{
        content: "";
        display: table;
        clear: both;
    }}
    
    .scrollable-chat {{
        height: 400px;
        overflow-y: auto;
        padding: 10px;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        background-color: #fafafa;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }}
    </style>
    
    <div class="scrollable-chat" id="scrollable-chat">
        {chat_messages_html}
    </div>
    
    <script>
    // Auto-scroll to bottom
    const container = document.getElementById('scrollable-chat');
    if (container) {{
        container.scrollTop = container.scrollHeight;
    }}
    </script>
    """, height=450)

def render_mobile_chat():
    """Render mobile-friendly chat interface with original custom styling"""
    # Check if we have a current conversation
    if not st.session_state.current_conversation_id:
        st.info("👈 Create or select a conversation to start chatting")
        return
    
    conv = get_current_conversation()
    if not conv:
        st.error("Conversation not found")
        return
    
    # Chat header with "Generate Summary" button on the right
    col1, col2 = st.columns([4, 1])
    
    with col1:
        st.markdown(f"### 💬 {conv.get('title', 'Untitled Conversation')}")
        st.caption(f"Session ID: `{conv['session_id']}`")
    with col2:
        if st.button("📝 Generate Summary", key="generate_summary", use_container_width=True):
            with st.spinner("Generating summary..."):
                response = call_api("Generate summary for this conversation.", conv["session_id"], generate_summary=True)
                if response:
                    process_response(response, conv["id"], summary=True)
                    st.success("✅ Summary generated!")
                    st.rerun()
                else:
                    st.error("Failed to generate summary")
    st.markdown("---")
    
    # Display chat messages using original custom interface
    render_custom_chat(conv)
    
    st.markdown("---")
    
    # Chat input (mobile-optimized)
    if prompt := st.chat_input("Type your message here...", key="chat_input"):
        # Add user message with local timezone
        conv["messages"].append({
            "role": "user",
            "content": prompt,
            "timestamp": datetime.now(LOCAL_TZ),
            "latency": None
        })
        
        # Update conversation title if this is the first user message
        if len([m for m in conv['messages'] if m['role'] == 'user']) == 1:
            update_conversation_title(conv['id'], prompt)
        
        save_conversations_to_storage()
        
        # Call API
        with st.spinner("Thinking..."):
            response = call_api(prompt, conv["session_id"])
            if response:
                process_response(response, conv['id'])
                st.rerun()
            else:
                st.error("Failed to get response from AI")

def render_sidebar_assessment():
    """Render assessment details in sidebar as expandable field"""
    # Check if we have a current conversation
    if not st.session_state.current_conversation_id:
        return
    
    conv = get_current_conversation()
    if not conv:
        return
    
    # Get current assessment state (from custom_outputs)
    state = conv.get('state', {})
    
    # Check if there's any meaningful data
    has_meaningful_data = bool(state and isinstance(state, dict) and any(
        v for k, v in state.items() 
        if k not in ['timestamp', 'session_id', 'user_language'] and v
    ))
    
    # Show expander with assessment details
    with st.expander("📋 Live Assessment", expanded=True):
        if has_meaningful_data:
            # Display result and reasoning
            if 'result' in state and state['result']:
                st.markdown(f"**Result:** `{state['result'].upper()}`")
                st.markdown("")

            # Display present symptoms
            if 'present_symptoms' in state and state['present_symptoms']:
                st.markdown("**Present Symptoms:**")
                for symptom_item in state['present_symptoms']:
                    if isinstance(symptom_item, dict):
                        symptom_name = symptom_item.get('symptom', 'Unknown')
                        st.markdown(f"- {symptom_name.title()}")
                        
                        details = symptom_item.get('details', [])
                        if details:
                            for detail in details:
                                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;- {detail}")
                st.markdown("")
            
            # Display absent symptoms
            if 'absent_symptoms' in state and state['absent_symptoms']:
                st.markdown("**Absent Symptoms:**")
                for symptom_item in state['absent_symptoms']:
                    if isinstance(symptom_item, dict):
                        symptom_name = symptom_item.get('symptom', 'Unknown')
                        st.markdown(f"- {symptom_name.title()}")
                st.markdown("")
            
            # Display risk factors
            if 'risk_factors' in state and state['risk_factors']:
                st.markdown("**Risk Factors:**")
                for symptom_item in state['risk_factors']:
                    if isinstance(symptom_item, dict):
                        symptom_name = symptom_item.get('symptom', 'Unknown')
                        st.markdown(f"- {symptom_name.title()}")
                        
                        details = symptom_item.get('details', [])
                        if details:
                            for detail in details:
                                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;- {detail}")
                st.markdown("")
        else:
            st.info("No assessment data yet")
    
    # Summary Section (if exists)
    if conv.get("summary"):
        with st.expander("📝 Summary", expanded=True):
            st.markdown(conv["summary"])
    
    st.markdown("---")


def render_mobile_assessment():
    """Placeholder - assessment now in sidebar"""
    pass

def main_app():
    """Main application interface"""
    init_session_state()
    
    # Render sidebar
    render_mobile_sidebar()
    
    # Main content area
    render_mobile_chat()
    
    # Assessment section
    render_mobile_assessment()

def login_page():
    """Login page with Google Sign-In"""
    st.title("🏥 AI Triage Demo")
    st.subheader("Login")
    
    # Try Google Sign-In first
    # render_google_signin_button()
    
    st.markdown("---")
    
    # Fallback: Simple email login
    st.markdown("### 📧 Sign in with email")
    st.markdown("Enter your authorized email to access the system.")
    
    email = st.text_input("Email Address", placeholder="your.email@example.com")
    
    if st.button("Continue with Email", use_container_width=True, type="primary"):
        if not email:
            st.error("❌ Please enter an email address.")
        elif not is_valid_email(email):
            st.error("❌ Please enter a valid email address.")
        else:
            # Check if email is authorized
            authorized_emails = st.secrets.get("AUTHORIZED_EMAILS", "").split(",")
            if is_email_authorized(email, authorized_emails):
                # Generate auth token
                auth_token = generate_auth_token(email)
                
                # Save to storage
                save_auth_to_storage(email, auth_token)
                
                # Set session state
                st.session_state.authenticated = True
                st.session_state.user_email = email
                
                st.success("✅ Login successful!")
                st.rerun()
            else:
                st.error("❌ Unauthorized email address or domain.")

def main():
    """Main application entry point"""
    init_session_state()
    
    # Check if authenticated via storage
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if not st.session_state.authenticated:
        # Try to load auth from storage
        auth_data = load_auth_from_storage()
        if auth_data and isinstance(auth_data, dict):
            if 'email' in auth_data and 'token' in auth_data:
                # Validate token is still valid (you can add expiration logic here if needed)
                st.session_state.authenticated = True
                st.session_state.user_email = auth_data['email']
    
    # Show appropriate page
    if st.session_state.authenticated:
        # Add user info and logout button in sidebar
        with st.sidebar:
            st.title("🏥 AI Triage")
            st.markdown("---")
            # Display logged in user email
            user_email = st.session_state.get('user_email', 'Unknown')
            st.markdown(f"**👤 Logged in as:**")
            st.markdown(f"`{user_email}`")
            st.markdown("")
            if st.button("🚪 Logout", use_container_width=True):
                st.session_state.authenticated = False
                st.session_state.user_email = None
                # Clear auth from storage
                clear_auth_from_storage()
                st.rerun()
        
        main_app()
    else:
        login_page()

if __name__ == "__main__":
    main()