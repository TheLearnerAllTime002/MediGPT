from flask import Flask, render_template, jsonify, request
from src.helper import download_hugging_face_embeddings
from langchain_pinecone import PineconeVectorStore
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
from src.prompt import system_prompt
import os
import logging
import markdown
import re

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

os.environ["PINECONE_API_KEY"] = PINECONE_API_KEY
os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY

embeddings = download_hugging_face_embeddings()

index_name = "medical-chatbot" 
docsearch = PineconeVectorStore.from_existing_index(
    index_name=index_name,
    embedding=embeddings
)

retriever = docsearch.as_retriever(search_type="similarity", search_kwargs={"k":3})

chatModel = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{input}"),
])

question_answer_chain = create_stuff_documents_chain(chatModel, prompt)
rag_chain = create_retrieval_chain(retriever, question_answer_chain)

def format_medical_response(text):
    # Convert markdown to HTML
    html = markdown.markdown(text, extensions=['nl2br', 'tables'])
    
    # Add medical-specific formatting
    html = re.sub(r'\*\*(.*?)\*\*', r'<strong class="medical-highlight">\1</strong>', html)
    html = re.sub(r'\*(.*?)\*', r'<em class="medical-emphasis">\1</em>', html)
    
    # Format symptoms, conditions, etc.
    html = re.sub(r'(Symptoms?|Causes?|Treatment|Diagnosis|Prevention):', 
                r'<h4 class="medical-section">\1:</h4>', html)
    
    return html

@app.route("/")
def index():
    return render_template('chat.html')

@app.route("/clear", methods=["POST"])
def clear_chat():
    return jsonify({"status": "Chat cleared"}), 200

@app.route("/get", methods=["GET", "POST"])
def chat():
    try:
        msg = request.form.get("msg", "").strip()
        
        if not msg:
            return jsonify({"error": "Empty message"}), 400
        
        if len(msg) > 1000:
            return jsonify({"error": "Message too long (max 1000 characters)"}), 400
        
        logger.info(f"User input: {msg}")
        
        # Invoke the RAG chain
        response = rag_chain.invoke({"input": msg})
        answer = response.get("answer", "No response generated")
        
        # Format the response
        formatted_answer = format_medical_response(answer)
        
        # Extract relevant documents if available
        context_docs = response.get("context", [])
        num_docs = len(context_docs) if context_docs else 0
        
        logger.info(f"Generated response using {num_docs} documents")
        
        return jsonify({
            "answer": formatted_answer,
            "raw_answer": answer,
            "num_documents": num_docs
        })
    
    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}", exc_info=True)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host="0.0.0.0", port=port, debug=False)