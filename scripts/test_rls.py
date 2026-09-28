import urllib.request, json
KEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZvdHl2ZmpicmptY2doZWthYXRrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzOTA3NDksImV4cCI6MjA4Nzk2Njc0OX0.-vo_fUfBzty-mPXn61tv-v8azBcXeL3nF0JBEgYopK0'
for tbl in ['customer_wishlist','conversations','products','messages']:
    r=urllib.request.Request('https://votyvfjbrjmcghekaatk.supabase.co/rest/v1/'+tbl+'?limit=1',headers={'apikey':KEY,'Authorization':'Bearer '+KEY})
    try:
        resp=urllib.request.urlopen(r)
        body=json.loads(resp.read())
        print(tbl, resp.getcode(), f'rows={len(body)}')
    except urllib.error.HTTPError as e:
        print(tbl, e.code, e.read()[:80].decode())
