import os

def update_all_html_branding():
    # 1. Update superadmin login files
    superadmin_login_files = [
        'static/superadmin_login.html',
        'superadmin/login.html',
        'superadmin/login/index.html'
    ]

    for p in superadmin_login_files:
        if not os.path.exists(p):
            continue
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace shield icon with logo
        old_header_1 = """        <!-- Header -->
        <div class="text-center mb-8">
            <div class="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-platform-500 to-platform-700 mb-4 shadow-lg shadow-platform-500/30">
                <i class="fas fa-shield-alt text-white text-2xl"></i>
            </div>
            <h1 class="text-2xl font-bold text-white">Sofía Platform</h1>
            <p class="text-gray-400 text-sm mt-1">Super Admin Console</p>
        </div>"""
            
        new_header = """        <!-- Header -->
        <div class="text-center mb-8">
            <div class="flex justify-center mb-3">
                <img src="images/synkrd-logo.png" onerror="this.src='/static/images/synkrd-logo.png'; this.onerror=function(){this.src='../images/synkrd-logo.png';};" alt="SynkRD" class="h-12 w-auto object-contain drop-shadow-md">
            </div>
            <p class="text-gray-400 text-xs uppercase tracking-wider font-semibold">Super Admin Console</p>
        </div>"""
            
        if old_header_1 in content:
            content = content.replace(old_header_1, new_header)
        elif 'src="/static/images/synkrd-logo.png"' in content:
            content = content.replace('src="/static/images/synkrd-logo.png"', 'src="images/synkrd-logo.png" onerror="this.src=\'/static/images/synkrd-logo.png\'; this.onerror=function(){this.src=\'../images/synkrd-logo.png\';};"')
            
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
        print('Updated superadmin login:', p)

    # 2. Update login files
    login_files = [
        'login.html',
        'static/login.html',
        'login/index.html'
    ]

    for p in login_files:
        if not os.path.exists(p):
            continue
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
            
        old_box = """            <div
                class="w-16 h-16 bg-gradient-to-br from-brand-400 to-brand-600 rounded-2xl flex items-center justify-center text-white text-2xl font-bold shadow-xl mx-auto mb-4 rotate-3 hover:rotate-0 transition-transform">
                S
            </div>
            <h1 class="text-3xl font-extrabold text-gray-800 dark:text-white tracking-tight">Sofía HQ</h1>
            <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">SynkDR Command Center</p>"""
                
        new_logo_block = """            <div class="flex justify-center mb-3">
                <img src="images/synkrd-logo.png" onerror="this.src='/static/images/synkrd-logo.png'; this.onerror=function(){this.src='../static/images/synkrd-logo.png';};" alt="SynkRD" class="h-14 w-auto object-contain drop-shadow-md">
            </div>
            <p class="text-xs text-gray-500 dark:text-gray-400 font-medium uppercase tracking-wider">Sofía AI Command Center</p>"""
                
        if old_box in content:
            content = content.replace(old_box, new_logo_block)
        elif 'src="static/images/synkrd-logo.png"' in content:
            content = content.replace('src="static/images/synkrd-logo.png"', 'src="images/synkrd-logo.png" onerror="this.src=\'/static/images/synkrd-logo.png\'; this.onerror=function(){this.src=\'../static/images/synkrd-logo.png\';};"')
            
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
        print('Updated login:', p)

    # 3. Update superadmin dashboard files
    superadmin_dash_files = [
        'superadmin.html',
        'static/superadmin.html',
        'superadmin/index.html'
    ]
    for p in superadmin_dash_files:
        if not os.path.exists(p):
            continue
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Ensure icon is loaded properly
        content = content.replace('src="static/images/synkrd-icon.png"', 'src="images/synkrd-icon.png" onerror="this.src=\'/static/images/synkrd-icon.png\'; this.onerror=function(){this.src=\'../static/images/synkrd-icon.png\';};"')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
        print('Updated superadmin dash:', p)

    # 4. Update admin dashboard files
    admin_dash_files = [
        'admin.html',
        'static/admin.html',
        'admin/index.html'
    ]
    for p in admin_dash_files:
        if not os.path.exists(p):
            continue
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
        
        content = content.replace('src="static/images/synkrd-logo.png"', 'src="images/synkrd-logo.png" onerror="this.src=\'/static/images/synkrd-logo.png\'; this.onerror=function(){this.src=\'../static/images/synkrd-logo.png\';};"')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
        print('Updated admin dash:', p)

    # 5. Update CRM files
    crm_files = [
        'crm.html',
        'static/crm.html',
        'crm/index.html'
    ]
    for p in crm_files:
        if not os.path.exists(p):
            continue
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
        
        content = content.replace('src="static/images/synkrd-logo.png"', 'src="images/synkrd-logo.png" onerror="this.src=\'/static/images/synkrd-logo.png\'; this.onerror=function(){this.src=\'../static/images/synkrd-logo.png\';};"')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
        print('Updated crm:', p)

    # 6. Update index.html
    if os.path.exists('index.html'):
        with open('index.html', 'r', encoding='utf-8') as f:
            content = f.read()
        content = content.replace('src="static/images/synkrd-logo.png"', 'src="images/synkrd-logo.png" onerror="this.src=\'static/images/synkrd-logo.png\';"')
        with open('index.html', 'w', encoding='utf-8') as f:
            f.write(content)
        print('Updated index.html')

if __name__ == '__main__':
    update_all_html_branding()
