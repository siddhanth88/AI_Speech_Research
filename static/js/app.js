// Get DOM elements
const fileInput = document.getElementById('fileInput');
const uploadArea = document.getElementById('uploadArea');
const fileInfo = document.getElementById('fileInfo');
const fileName = document.getElementById('fileName');
const removeFile = document.getElementById('removeFile');
const convertBtn = document.getElementById('convertBtn');

const uploadSection = document.getElementById('uploadSection');
const processingSection = document.getElementById('processingSection');
const successSection = document.getElementById('successSection');
const errorSection = document.getElementById('errorSection');

const processingStatus = document.getElementById('processingStatus');
const progressFill = document.getElementById('progressFill');
const progressText = document.getElementById('progressText');

const audioFileName = document.getElementById('audioFileName');
const audioFileSize = document.getElementById('audioFileSize');
const downloadBtn = document.getElementById('downloadBtn');
const errorMessage = document.getElementById('errorMessage');

const convertAnotherBtn = document.getElementById('convertAnotherBtn');
const tryAgainBtn = document.getElementById('tryAgainBtn');

let selectedFile = null;

console.log('App initialized');

// File input change handler
fileInput.addEventListener('change', (e) => {
    console.log('File input changed');
    const file = e.target.files[0];
    console.log('Selected file:', file);
    
    if (file && file.type === 'application/pdf') {
        selectedFile = file;
        showFileInfo(file.name);
        console.log('File accepted:', file.name, 'Size:', (file.size / 1024 / 1024).toFixed(2), 'MB');
    } else {
        console.error('Invalid file type:', file ? file.type : 'no file');
        alert('Please select a PDF file');
    }
});

// Drag and drop handlers
uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.style.borderColor = 'var(--primary)';
    uploadArea.style.background = 'var(--bg-light)';
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.style.borderColor = '';
    uploadArea.style.background = '';
});

uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    console.log('File dropped');
    uploadArea.style.borderColor = '';
    uploadArea.style.background = '';
    
    const file = e.dataTransfer.files[0];
    console.log('Dropped file:', file);
    
    if (file && file.type === 'application/pdf') {
        selectedFile = file;
        showFileInfo(file.name);
        console.log('File accepted:', file.name);
    } else {
        console.error('Invalid file type:', file ? file.type : 'no file');
        showError('Please upload a PDF file');
    }
});

// Show file info
function showFileInfo(name) {
    console.log('Showing file info:', name);
    fileName.textContent = name;
    fileInfo.style.display = 'flex';
    uploadArea.style.display = 'none';
    convertBtn.disabled = false;
}

// Remove file
removeFile.addEventListener('click', () => {
    console.log('Removing file');
    selectedFile = null;
    fileInput.value = '';
    fileInfo.style.display = 'none';
    uploadArea.style.display = 'block';
    convertBtn.disabled = true;
});

// Convert button click
convertBtn.addEventListener('click', async () => {
    console.log('Convert button clicked');
    
    if (!selectedFile) {
        console.error('No file selected');
        alert('Please select a PDF file first');
        return;
    }
    
    console.log('Starting conversion for:', selectedFile.name);
    showSection('processing');
    
    const formData = new FormData();
    formData.append('file', selectedFile);
    
    console.log('FormData created with file:', selectedFile.name);
    
    try {
        // Simulate progress
        simulateProgress();
        
        console.log('Sending upload request...');
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        
        console.log('Response status:', response.status);
        
        const data = await response.json();
        console.log('Response data:', data);
        
        if (response.ok && data.success) {
            console.log('Upload successful!');
            showSuccess(data);
        } else {
            console.error('Upload failed:', data.error);
            showError(data.error || 'Conversion failed');
        }
    } catch (error) {
        console.error('Network error:', error);
        showError('Network error: ' + error.message);
    }
});

// Simulate progress
function simulateProgress() {
    let progress = 0;
    const interval = setInterval(() => {
        progress += Math.random() * 10;
        if (progress > 90) {
            progress = 90;
            clearInterval(interval);
        }
        updateProgress(progress);
    }, 800);
}

// Update progress
function updateProgress(percent) {
    progressFill.style.width = percent + '%';
    progressText.textContent = Math.round(percent) + '%';
    
    if (percent < 20) {
        processingStatus.textContent = 'Extracting text from PDF...';
    } else if (percent < 40) {
        processingStatus.textContent = 'Cleaning and enhancing text...';
    } else if (percent < 70) {
        processingStatus.textContent = 'Generating natural speech...';
    } else {
        processingStatus.textContent = 'Combining audio files...';
    }
}

// Show success
function showSuccess(data) {
    console.log('Showing success:', data);
    updateProgress(100);
    
    setTimeout(() => {
        audioFileName.textContent = data.filename;
        audioFileSize.textContent = data.size;
        downloadBtn.href = data.download_url;
        
        // Load audio player
        const audioPlayer = document.getElementById('audioPlayer');
        const audioSource = document.getElementById('audioSource');
        
        if (audioPlayer && audioSource) {
            audioSource.src = data.download_url;
            audioPlayer.load();
            console.log('✅ Audio player loaded with:', data.download_url);
        }
        
        showSection('success');
    }, 500);
}

// Show error
function showError(message) {
    console.error('Showing error:', message);
    errorMessage.textContent = message;
    showSection('error');
}

// Show section
function showSection(section) {
    console.log('Showing section:', section);
    
    uploadSection.style.display = 'none';
    processingSection.style.display = 'none';
    successSection.style.display = 'none';
    errorSection.style.display = 'none';
    
    switch(section) {
        case 'upload':
            uploadSection.style.display = 'block';
            break;
        case 'processing':
            processingSection.style.display = 'block';
            updateProgress(0);
            break;
        case 'success':
            successSection.style.display = 'block';
            break;
        case 'error':
            errorSection.style.display = 'block';
            break;
    }
}

// Convert another / try again buttons
convertAnotherBtn.addEventListener('click', () => {
    console.log('Convert another clicked');
    selectedFile = null;
    fileInput.value = '';
    fileInfo.style.display = 'none';
    uploadArea.style.display = 'block';
    convertBtn.disabled = true;
    showSection('upload');
});

tryAgainBtn.addEventListener('click', () => {
    console.log('Try again clicked');
    showSection('upload');
});

// Test server connection on load
fetch('/test')
    .then(res => res.json())
    .then(data => {
        console.log('✅ Server test successful:', data);
    })
    .catch(err => {
        console.error('❌ Server test failed:', err);
        alert('Cannot connect to server. Make sure Python server is running!');
    });