import streamlit as st
import streamlit_authenticator as stauth
import requests
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List
import yaml
from yaml.loader import SafeLoader
import os
import pickle

# Page configuration
st.set_page_config(
    page_title="AI Triage Demo",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load configuration
@st.cache_data
def load_config():
    try:
        with open('config.yaml') as file:
            config = yaml.load(file, Loader=SafeLoader)
        return config
    except FileNotFoundError:
        # Fallback to secrets for deployment
        return {
            'cookie': {
                'expiry_days': 30,
                'key': st.secrets.get("COOKIE_KEY", "default_key"),
                'name': st.secrets.get("COOKIE_NAME", "ai_triage_cookie")
            }
        }

# Initialize session state
def init_session_state():
    if "conversations" not in st.session_state:
        st.session_state.conversations = {}
    if "current_conversation_id" not in st.session_state:
        st.session_state.current_conversation_id = None
    if "patient_info" not in st.session_state:
        st.session_state.patient_info = {"age": 35, "gender": "Male"}
    if "current_state" not in st.session_state:
        st.session_state.current_state = {}
    if "current_summary" not in st.session_state:
        st.session_state.current_summary = ""

def is_email_authorized(email, authorized_list):
    """Check if email is authorized - supports individual emails and domain wildcards"""
    email = email.strip().lower()
    
    for authorized_item in authorized_list:
        authorized_item = authorized_item.strip().lower()
        
        # Check for domain wildcard (e.g., @whitecoat.global)
        if authorized_item.startswith('@'):
            domain = authorized_item[1:]  # Remove the @
            if email.endswith('@' + domain):
                return True
        
        # Check for exact email match
        elif email == authorized_item:
            return True
    
    return False

# Simple file-based persistence
def get_user_conversations_file(user_email):
    """Get file path for user's conversations"""
    os.makedirs("user_data", exist_ok=True)
    safe_email = user_email.replace("@", "_at_").replace(".", "_dot_")
    return f"user_data/{safe_email}_conversations.pkl"

def save_conversations(user_email):
    """Save conversations to file"""
    try:
        file_path = get_user_conversations_file(user_email)
        with open(file_path, 'wb') as f:
            pickle.dump(st.session_state.conversations, f)
    except Exception as e:
        st.error(f"Failed to save conversations: {str(e)}")

def load_conversations(user_email):
    """Load conversations from file"""
    try:
        file_path = get_user_conversations_file(user_email)
        if os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                return pickle.load(f)
        return {}
    except Exception as e:
        st.error(f"Failed to load conversations: {str(e)}")
        return {}

def get_current_user_email():
    """Get current user email"""
    if hasattr(st.session_state, 'user_email'):
        return st.session_state.user_email
    elif hasattr(st.session_state, 'username') and hasattr(st.session_state, 'name'):
        return getattr(st.session_state, 'user_email', 'default_user@example.com')
    return 'default_user@example.com'

# API configuration
API_BASE_URL = st.secrets.get("API_BASE_URL", "https://dbc-e469a72f-3a02.cloud.databricks.com/serving-endpoints/agents_gen_ai-ai_triage-ai_triage_langgraph_v4")
DATABRICKS_TOKEN = st.secrets.get("DATABRICKS_TOKEN", "your_token_here")

def call_api(user_message: str, session_id: str, generate_summary: bool = False) -> Dict[str, Any]:
    """Call the AI agent API using Databricks serving endpoint format"""
    headers = {"Content-Type": "application/json"}
    
    # Use basic auth with token as username and token as password
    auth = ("token", DATABRICKS_TOKEN)
    
    payload = {
        "messages": [{"role": "user", "content": user_message}],
        "custom_inputs": {
            "session_id": session_id,
            "gender": st.session_state.patient_info["gender"],
            "age": st.session_state.patient_info["age"]
        }
    }
    
    print('payload:', payload)
    print()

    # Only add generate_summary flag when explicitly requested
    if generate_summary:
        payload["custom_inputs"]["generate_summary"] = True
    
    try:
        # Record start time
        start_time = datetime.now()
        
        # Use the invocations endpoint
        url = f"{API_BASE_URL}/invocations"
        response = requests.post(url, json=payload, headers=headers, auth=auth)
        response.raise_for_status()
        
        # Calculate actual latency
        end_time = datetime.now()
        latency = (end_time - start_time).total_seconds()
        
        result = response.json()
        
        # Add latency to the response
        result["_latency"] = round(latency, 2)

        print('result:', result)
        print()
        
        return result
    except Exception as e:
        st.error(f"API Error: {str(e)}")
        print(str(e))
        return None

def create_new_conversation():
    """Create a new conversation with initial template message"""
    conversation_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())  # Separate session_id for API
    initial_message = "Hi, I'm your AI Triage Chatbot. I'm here to discuss your symptoms and help guide you to the next appropriate care option. Could you please describe any symptoms you are experiencing?"
    
    st.session_state.conversations[conversation_id] = {
        "id": conversation_id,
        "session_id": session_id,  # Store session_id separately
        "title": f"Conversation {len(st.session_state.conversations) + 1}",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "messages": [{"role": "assistant", "content": initial_message, "timestamp": datetime.now(), "latency": None}],
        "state": {},
        "summary": ""
    }
    
    st.session_state.current_conversation_id = conversation_id
    st.session_state.current_state = {}
    st.session_state.current_summary = ""
    
    # Save to file storage
    user_email = get_current_user_email()
    save_conversations(user_email)

def get_current_conversation():
    """Get the current conversation or create one if none exists"""
    if not st.session_state.current_conversation_id or st.session_state.current_conversation_id not in st.session_state.conversations:
        create_new_conversation()
    return st.session_state.conversations[st.session_state.current_conversation_id]

def generate_summary():
    """Generate summary for current conversation"""
    if not st.session_state.current_conversation_id:
        st.error("No active conversation to summarize")
        return
    
    with st.spinner("Generating summary..."):
        conversation = get_current_conversation()
        session_id = conversation.get("session_id", str(uuid.uuid4()))
        summary_message = "Please generate a summary of this conversation"
        
        # Explicitly request summary generation
        response = call_api(user_message=summary_message, session_id=session_id, generate_summary=True)
        
        if response:
            summary = None
            
            # Check if summary is in custom_outputs
            if "custom_outputs" in response and "summary" in response["custom_outputs"]:
                summary = response["custom_outputs"]["summary"]
            
            # If not in custom_outputs, check if it's in the messages
            elif "messages" in response and response["messages"]:
                summary = response["messages"][0].get("content", "")
            
            # If we found a summary, store it
            if summary:
                st.session_state.conversations[st.session_state.current_conversation_id]["summary"] = summary
                st.session_state.current_summary = summary
                
                # Save to file storage
                user_email = get_current_user_email()
                save_conversations(user_email)
                st.success("Summary generated successfully!")
            else:
                st.error("Summary not found in response")
        else:
            st.error("Failed to generate summary")

def auto_generate_summary_if_needed():
    """Auto-generate summary when result becomes available"""
    if (st.session_state.current_conversation_id and 
        st.session_state.current_state and 
        "result" in st.session_state.current_state and
        st.session_state.current_state["result"] is not None):
        
        # Check if result is suitable or not_suitable
        result = str(st.session_state.current_state["result"]).lower()
        if result in ["suitable", "not_suitable"]:
            # Check if summary hasn't been generated yet
            current_conv = st.session_state.conversations[st.session_state.current_conversation_id]
            if not current_conv.get("summary", "").strip() and not st.session_state.get("auto_summary_pending", False):
                # Mark that auto-summary is pending (to prevent multiple calls)
                st.session_state.auto_summary_pending = True

def main_app():
    """Main application after authentication"""
    init_session_state()
    
    # Load conversations for current user
    user_email = get_current_user_email()
    if not st.session_state.conversations:
        st.session_state.conversations = load_conversations(user_email)
    
    st.title("🏥 AI Triage Demo")
    
    # Create three columns for layout (giving more space to right sidebar)
    left_col, middle_col, right_col = st.columns([0.7, 2.0, 1.3])
    
    # Left Sidebar - Conversations
    with left_col:
        # New conversation button
        if st.button("➕ New Conversation", use_container_width=True):
            create_new_conversation()
        
        st.subheader("💬 Conversations")
        
        # List existing conversations with delete functionality
        if st.session_state.conversations:
            for conv_id, conv in st.session_state.conversations.items():
                is_current = conv_id == st.session_state.current_conversation_id
                button_style = "📌 " if is_current else ""
                
                # Create columns for conversation button and delete button
                conv_col, delete_col = st.columns([4, 1])
                
                with conv_col:
                    if st.button(
                        f"{button_style} {conv['title']}\n{conv['created_at']}", 
                        key=f"conv_{conv_id}",
                        use_container_width=True
                    ):
                        st.session_state.current_conversation_id = conv_id
                        st.session_state.current_state = conv.get("state", {})
                        st.session_state.current_summary = conv.get("summary", "")
                        st.rerun()
                
                with delete_col:
                    if st.button("❌", key=f"delete_{conv_id}", help="Delete conversation"):
                        # Don't delete if it's the current conversation and it's the only one
                        if len(st.session_state.conversations) == 1:
                            st.error("Cannot delete the last conversation")
                        else:
                            # Delete the conversation
                            del st.session_state.conversations[conv_id]
                            
                            # If we deleted the current conversation, switch to another one
                            if conv_id == st.session_state.current_conversation_id:
                                if st.session_state.conversations:
                                    # Switch to the first available conversation
                                    new_conv_id = list(st.session_state.conversations.keys())[0]
                                    st.session_state.current_conversation_id = new_conv_id
                                    st.session_state.current_state = st.session_state.conversations[new_conv_id].get("state", {})
                                    st.session_state.current_summary = st.session_state.conversations[new_conv_id].get("summary", "")
                                else:
                                    # No conversations left, create a new one
                                    create_new_conversation()
                            
                            # Save to file storage
                            user_email = get_current_user_email()
                            save_conversations(user_email)
                            st.rerun()
        else:
            st.info("No conversations yet. Create a new one!")
    
    # Middle Column - Chat Interface
    with middle_col:
        st.subheader("💬 Chat")
        
        # Show full session ID below the Chat title
        current_conv = get_current_conversation()
        if current_conv.get("session_id"):
            st.markdown(f"**Session ID:** `{current_conv['session_id']}`")
            st.markdown("---")
        
        # Create scrollable chat container with HTML and internal CSS
        chat_messages_html = ""
        for message in current_conv["messages"]:
            # Use real timestamp if available, otherwise generate one
            if "timestamp" in message:
                timestamp = message["timestamp"].strftime("%H:%M")
            else:
                timestamp = datetime.now().strftime("%H:%M")
            
            if message["role"] == "user":
                chat_messages_html += f"""
                <div class="message-container">
                    <div class="user-message">
                        {message["content"]}
                    </div>
                    <div class="user-timestamp">
                        {timestamp}
                    </div>
                </div>
                """
            else:
                # For AI messages, include latency if available
                latency_text = ""
                if "latency" in message and message["latency"] is not None:
                    latency_text = f" • {message['latency']}s"
                
                chat_messages_html += f"""
                <div class="message-container">
                    <div class="assistant-message">
                        {message["content"]}
                    </div>
                    <div class="assistant-timestamp">
                        {timestamp}{latency_text}
                    </div>
                </div>
                """
        
        # Display chat with CSS inside the HTML component
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
        
        # Check if we need to auto-generate summary (after chat messages are displayed)
        if st.session_state.get("auto_summary_pending", False):
            st.session_state.auto_summary_pending = False
            
            # Auto-generate summary
            conversation = get_current_conversation()
            session_id = conversation.get("session_id", str(uuid.uuid4()))
            summary_message = "Please generate a summary of this conversation"
            
            # Explicitly request summary generation
            with st.spinner("Auto-generating summary..."):
                response = call_api(user_message=summary_message, session_id=session_id, generate_summary=True)
                
                if response:
                    summary = None
                    
                    # Check if summary is in custom_outputs
                    if "custom_outputs" in response and "summary" in response["custom_outputs"]:
                        summary = response["custom_outputs"]["summary"]
                    
                    # If not in custom_outputs, check if it's in the messages
                    elif "messages" in response and response["messages"]:
                        summary = response["messages"][0].get("content", "")
                    
                    # If we found a summary, store it
                    if summary:
                        st.session_state.conversations[st.session_state.current_conversation_id]["summary"] = summary
                        st.session_state.current_summary = summary
                        
                        # Save to file storage
                        user_email = get_current_user_email()
                        save_conversations(user_email)
                        
                        st.success("✨ Summary auto-generated!")
                        st.rerun()
        
        # Check if we need to get AI response for the last user message
        if (current_conv["messages"] and 
            current_conv["messages"][-1]["role"] == "user" and 
            not st.session_state.get("processing_response", False)):
            
            # Set flag to prevent multiple API calls
            st.session_state.processing_response = True
            
            last_user_msg = current_conv["messages"][-1]["content"]
            session_id = current_conv.get("session_id", str(uuid.uuid4()))
            
            # Get AI response
            with st.spinner("Thinking..."):
                response = call_api(user_message=last_user_msg, session_id=session_id, generate_summary=False)
                
                if response:
                    # Extract assistant message
                    if "messages" in response and response["messages"]:
                        assistant_message = response["messages"][0]["content"]
                    else:
                        assistant_message = response.get("content", "I apologize, but I couldn't generate a response.")
                    
                    # Update state first
                    if "custom_outputs" in response:
                        current_conv["state"] = response["custom_outputs"]
                        st.session_state.current_state = response["custom_outputs"]
                    
                    # Add assistant message with real latency
                    current_conv["messages"].append({
                        "role": "assistant", 
                        "content": assistant_message,
                        "timestamp": datetime.now(),
                        "latency": response.get("_latency", None)
                    })
                    
                    # Clear the processing flag
                    st.session_state.processing_response = False
                    
                    # Save to file storage
                    user_email = get_current_user_email()
                    save_conversations(user_email)
                    
                    # Check if we should auto-generate summary (but don't interrupt the flow)
                    auto_generate_summary_if_needed()
                    
                    # Rerun to show the AI response
                    st.rerun()
                else:
                    error_msg = "Sorry, I encountered an error. Please try again."
                    current_conv["messages"].append({
                        "role": "assistant", 
                        "content": error_msg,
                        "timestamp": datetime.now(),
                        "latency": None
                    })
                    st.session_state.processing_response = False
                    
                    # Save to file storage
                    user_email = get_current_user_email()
                    save_conversations(user_email)
                    st.rerun()
        
        # Custom chat input that stays in the middle column
        st.markdown("---")
        
        # Create input form with columns for better control
        with st.form(key="chat_form", clear_on_submit=True):
            input_col1, input_col2 = st.columns([4, 1])
            
            with input_col1:
                user_input = st.text_input(
                    "Message",
                    placeholder="Describe your symptoms...",
                    label_visibility="collapsed"
                )
            
            with input_col2:
                send_button = st.form_submit_button("Send", use_container_width=True)
            
            # Handle input submission
            if send_button and user_input.strip():
                # Get the session_id for this conversation - ENSURE it's created and persisted
                if "session_id" not in current_conv or not current_conv["session_id"]:
                    current_conv["session_id"] = str(uuid.uuid4())
                
                # Clear any existing processing flag
                st.session_state.processing_response = False
                
                # Add user message with timestamp and display immediately
                current_conv["messages"].append({
                    "role": "user", 
                    "content": user_input,
                    "timestamp": datetime.now(),
                    "latency": None
                })
                
                # Trigger rerun to show user message immediately
                st.rerun()
    
    # Right Sidebar - Patient Info and State
    with right_col:
        # Logout button at top right
        if st.button("Logout", key="logout_btn"):
            st.session_state.authenticated = False
            st.session_state.clear()
            # Clear query params
            try:
                st.experimental_set_query_params()
            except AttributeError:
                # Query params not available in this version
                pass
            st.rerun()
        
        # Generate summary button
        if st.button("📋 Generate Summary", use_container_width=True):
            generate_summary()
        
        # Display summary immediately below the generate summary button
        if st.session_state.current_summary:
            st.markdown("**📋 Summary:**")
            with st.expander("Summary", expanded=True):
                st.markdown(st.session_state.current_summary)
            st.markdown("---")
        
        st.subheader("👤 Patient Info")
        
        # Patient information inputs
        age = st.slider(
            "Age",
            min_value=0,
            max_value=110,
            value=st.session_state.patient_info["age"],
            key="age_input"
        )
        
        gender = st.selectbox(
            "Gender",
            options=["Male", "Female", "Other"],
            index=["Male", "Female", "Other"].index(st.session_state.patient_info["gender"]),
            key="gender_input"
        )
        
        # Update patient info
        st.session_state.patient_info["age"] = age
        st.session_state.patient_info["gender"] = gender
        
        st.markdown("---")
        
        # Display current state with better formatting and reordered sections
        st.subheader("📊 Live Assessment State")
        
        if st.session_state.current_state:
            # Check if we have any meaningful data to display
            has_meaningful_data = False
            
            # Check for result
            has_result = ("result" in st.session_state.current_state and 
                         st.session_state.current_state["result"] is not None)
            
            # Check for actual data in the sections we care about
            section_order = ["present_symptoms", "absent_symptoms", "risk_factors"]
            for section_key in section_order:
                if section_key in st.session_state.current_state:
                    value = st.session_state.current_state[section_key]
                    if isinstance(value, dict) and value:
                        has_meaningful_data = True
                        break
                    elif isinstance(value, list) and value:
                        has_meaningful_data = True
                        break
                    elif value and not isinstance(value, (dict, list)):
                        has_meaningful_data = True
                        break
            
            # If we have result OR meaningful data, show the assessment
            if has_result or has_meaningful_data:
                # Display Result at the top with color coding
                if has_result:
                    result = str(st.session_state.current_state["result"]).lower()
                    if result == "suitable":
                        st.markdown(f"""
                        <div style="background-color: #d4edda; color: #155724; padding: 10px; border-radius: 5px; margin: 5px 0;">
                            <strong>🟢 Result: Suitable</strong>
                        </div>
                        """, unsafe_allow_html=True)
                    elif result == "not_suitable":
                        st.markdown(f"""
                        <div style="background-color: #f8d7da; color: #721c24; padding: 10px; border-radius: 5px; margin: 5px 0;">
                            <strong>🔴 Result: Unsuitable</strong>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
                        <div style="background-color: #f8f9fa; color: #6c757d; padding: 10px; border-radius: 5px; margin: 5px 0;">
                            <strong>⚪ Result: {result.title()}</strong>
                        </div>
                        """, unsafe_allow_html=True)
                
                # Display other sections in the specified order (only if they have data)
                for section_key in section_order:
                    if section_key in st.session_state.current_state:
                        value = st.session_state.current_state[section_key]
                        
                        # Check if section has data before showing header
                        has_data = False
                        if isinstance(value, dict) and value:
                            has_data = True
                        elif isinstance(value, list) and value:
                            has_data = True
                        elif value and not isinstance(value, (dict, list)):
                            has_data = True
                        
                        if has_data:
                            st.markdown(f"**{section_key.replace('_', ' ').title()}:**")
                            
                            if isinstance(value, dict):
                                # Handle nested dictionaries (like symptoms) with better indentation
                                for sub_key, sub_value in value.items():
                                    # Skip generic keys like "symptom" and "details" - show the actual content
                                    if sub_key.lower() in ["symptom", "details"]:
                                        if isinstance(sub_value, list):
                                            for item in sub_value:
                                                if sub_key.lower() == "symptom":
                                                    st.markdown(f"&nbsp;&nbsp;• **{item}**")
                                                else:  # details
                                                    st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;◦ {item}")
                                        else:
                                            if sub_key.lower() == "symptom":
                                                st.markdown(f"&nbsp;&nbsp;• **{sub_value}**")
                                            else:  # details
                                                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;◦ {sub_value}")
                                    else:
                                        # For other keys, show as before
                                        st.markdown(f"&nbsp;&nbsp;• **{sub_key}**")
                                        if isinstance(sub_value, list):
                                            for item in sub_value:
                                                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;◦ {item}")
                                        else:
                                            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;◦ {sub_value}")
                            
                            elif isinstance(value, list):
                                # Handle lists with proper indentation
                                for item in value:
                                    if isinstance(item, dict):
                                        # Handle list of dictionaries - group symptom and details together
                                        symptom_name = None
                                        details = []
                                        
                                        for sub_key, sub_value in item.items():
                                            if sub_key.lower() == "symptom":
                                                if isinstance(sub_value, list):
                                                    symptom_name = sub_value[0] if sub_value else "Unknown"
                                                else:
                                                    symptom_name = sub_value
                                            elif sub_key.lower() == "details":
                                                if isinstance(sub_value, list):
                                                    details.extend(sub_value)
                                                else:
                                                    details.append(sub_value)
                                            else:
                                                # For other keys, treat as regular nested data
                                                if not symptom_name:  # Only if we haven't found a symptom yet
                                                    st.markdown(f"&nbsp;&nbsp;• **{sub_key}**")
                                                    if isinstance(sub_value, list):
                                                        for sub_item in sub_value:
                                                            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;◦ {sub_item}")
                                                    else:
                                                        st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;◦ {sub_value}")
                                        
                                        # Display the symptom and its details if found
                                        if symptom_name:
                                            st.markdown(f"&nbsp;&nbsp;• **{symptom_name}**")
                                            for detail in details:
                                                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;◦ {detail}")
                                    else:
                                        st.markdown(f"&nbsp;&nbsp;• {item}")
                            
                            else:
                                # Handle simple values
                                st.markdown(f"&nbsp;&nbsp;• {value}")
                            
                            st.markdown("")  # Add spacing between sections
            else:
                # No meaningful data - show the info message
                st.info("No assessment state available")
        else:
            st.info("No assessment state available")
        
        st.markdown("---")
    
    # Footer
    st.markdown("---")
    st.markdown(
        "<small>This is an AI-powered triage system. For medical emergencies, please call emergency services immediately.</small>",
        unsafe_allow_html=True
    )

def main():
    """Main application entry point"""
    # Check if running in deployment mode (with secrets)
    if hasattr(st, 'secrets') and "AUTHORIZED_EMAILS" in st.secrets:
        # Simple email-based authentication for deployment with persistence
        if "authenticated" not in st.session_state:
            st.session_state.authenticated = False
        
        # Check for saved authentication in query params (simple persistence)
        try:
            query_params = st.experimental_get_query_params()
        except AttributeError:
            # Fallback for even older versions
            query_params = {}
            
        if "auth_token" in query_params and not st.session_state.authenticated:
            # Simple token check (in production, use proper JWT or similar)
            auth_token = query_params["auth_token"][0] if isinstance(query_params["auth_token"], list) else query_params["auth_token"]
            if auth_token == "authenticated_user":  # Simple check
                st.session_state.authenticated = True
                user_email = query_params.get("user_email", ["user@example.com"])
                st.session_state.user_email = user_email[0] if isinstance(user_email, list) else user_email
        
        if not st.session_state.authenticated:
            st.title("🏥 AI Triage Demo - Login")
            st.markdown("Please enter your authorized email to access the system.")
            
            email = st.text_input("Email Address")
            
            if st.button("Login"):
                authorized_emails = st.secrets["AUTHORIZED_EMAILS"].split(",")
                if is_email_authorized(email, authorized_emails):
                    st.session_state.authenticated = True
                    st.session_state.user_email = email.strip()
                    
                    # Set query params for persistence
                    try:
                        st.experimental_set_query_params(
                            auth_token="authenticated_user",
                            user_email=email.strip()
                        )
                    except AttributeError:
                        # Query params not available in this version
                        pass
                    
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.error("Unauthorized email address or domain.")
        else:
            main_app()
    else:
        # Local development mode - load config file
        try:
            config = load_config()
            
            # Create authenticator
            authenticator = stauth.Authenticate(
                config['credentials'],
                config['cookie']['name'],
                config['cookie']['key'],
                config['cookie']['expiry_days']
            )
            
            # Login widget
            name, authentication_status, username = authenticator.login('Login', 'main')
            
            if authentication_status == False:
                st.error('Username/password is incorrect')
            elif authentication_status == None:
                st.warning('Please enter your username and password')
            elif authentication_status:
                # Store user email for persistence
                if username in config['credentials']['usernames']:
                    st.session_state.user_email = config['credentials']['usernames'][username]['email']
                
                # Show logout
                authenticator.logout('Logout', 'sidebar')
                st.sidebar.write(f'Welcome *{name}*')
                
                main_app()
                
        except Exception as e:
            st.error(f"Authentication setup error: {str(e)}")
            st.info("Running in development mode without authentication")
            main_app()

if __name__ == "__main__":
    main()