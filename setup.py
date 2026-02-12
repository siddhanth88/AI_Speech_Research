"""
Quick Setup Script - Run this to organize your files
"""

import os
import shutil

# Create templates folder
os.makedirs('templates', exist_ok=True)
os.makedirs('uploads', exist_ok=True)
os.makedirs('outputs', exist_ok=True)

# Copy index.html to templates folder
if os.path.exists('index.html'):
    shutil.copy('index.html', 'templates/index.html')
    print("✅ Copied index.html to templates/")
elif os.path.exists('index_new.html'):
    shutil.copy('index_new.html', 'templates/index.html')
    print("✅ Copied index_new.html to templates/index.html")
else:
    print("❌ No HTML file found!")

print("\n🎉 Setup complete!")
print("\nNow run: python app_no_ffmpeg.py")