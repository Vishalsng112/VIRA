# testing commands I am using to test the API endpoints

curl -c cookies.ck -X POST http://127.0.0.1:8000/api/login -H "Content-Type: application/json" -d '{"username":"vishal","password":"vishal"}'
echo "Cookies saved to cookies.ck"

# access the health endpoint using the saved cookies
curl -b cookies.ck http://127.0.0.1:8000/health | jq


# chatbot endpoint example using the saved cookies
# curl -X POST -b cookies.ck http://localhost:8000/chat -H "Content-Type: application/json" -d '{"message": "Hello, how are you?"}'


# curl -X POST -b cookies.ck http://127.0.0.1:8000/chat \k http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d '{"message": "Hello, how are you?"}'


# curl -X POST -b cookies.ck http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d '{"message": "My Name is Vishal SINGH ?", "conversation_id": "test-conversation-123"}' | jq
