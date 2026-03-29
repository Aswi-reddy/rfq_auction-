from rfq_auction.wsgi import application

# For Vercel serverless function
def handler(request):
    return application(request.environ, request.start_response)
