<!DOCTYPE html>
<html lang="fa">
<head>
<meta charset="UTF-8">
<title>نصب Radar Sonar Bot</title>
<style>
body {
    font-family: Tahoma, sans-serif;
    background: #0f172a;
    color: #e5e7eb;
    direction: rtl;
    padding: 20px;
}
h1, h2 {
    color: #38bdf8;
}
pre {
    background: #020617;
    padding: 15px;
    border-radius: 8px;
    overflow-x: auto;
}
button {
    background: #2563eb;
    color: white;
    border: none;
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
}
button:hover {
    background: #1d4ed8;
}
.code-box {
    position: relative;
    margin-bottom: 15px;
}
.copy-btn {
    position: absolute;
    left: 10px;
    top: 10px;
}
hr {
    border: 1px solid #1e293b;
    margin: 25px 0;
}
</style>

<script>
function copyText(id) {
    const text = document.getElementById(id).innerText;
    navigator.clipboard.writeText(text);
    alert("کپی شد ✅");
}
</script>
</head>

<body>

<h1>🚀 Radar Sonar Bot</h1>

<p>ربات مانیتورینگ و مدیریت سرور از طریق تلگرام  
سبک، پایدار، امن و مناسب برای VPS و سرورهای بین‌المللی</p>

<hr>

<h2>✨ امکانات</h2>
<ul>
<li>مانیتور CPU، RAM، Disk، Uptime</li>
<li>هشدار قطعی و افت کیفیت</li>
<li>ارسال لاگ و آمار به تلگرام</li>
<li>مدیریت چند سرور همزمان</li>
<li>سیستم دسترسی ادمین</li>
<li>دیتابیس SQLite</li>
<li>کنترل از طریق CLI</li>
</ul>

<hr>

<h2>⚡ نصب سریع با یک دستور (Bash)</h2>

<div class="code-box">
<button class="copy-btn" onclick="copyText('cmd1')">📋 کپی</button>
<pre><code id="cmd1">curl -sL https://raw.githubusercontent.com/Amirtn9/Radar-Sonar/main/install.sh | bash</code></pre>
</div>

<p>یا به صورت دستی:</p>

<div class="code-box">
<button class="copy-btn" onclick="copyText('cmd2')">📋 کپی</button>
<pre><code id="cmd2">wget https://raw.githubusercontent.com/Amirtn9/Radar-Sonar/main/install.sh</code></pre>
</div>

<div class="code-box">
<button class="copy-btn" onclick="copyText('cmd3')">📋 کپی</button>
<pre><code id="cmd3">chmod +x install.sh
./install.sh</code></pre>
</div>

<hr>

<h2>📦 پیش‌نیازها</h2>
<ul>
<li>Ubuntu 20.04 یا 22.04</li>
<li>Python 3.10+</li>
<li>دسترسی root</li>
<li>اتصال اینترنت</li>
</ul>

<hr>

<h2>📂 ساختار پروژه</h2>

<pre><code>
Radar-Sonar/
│
├── bot.py
├── config.py
├── database.db
├── install.sh
├── requirements.txt
└── README.md
</code></pre>

<hr>

<h2>🛠 دستورات مدیریتی</h2>

<div class="code-box">
<button class="copy-btn" onclick="copyText('cmd4')">📋 کپی</button>
<pre><code id="cmd4">sonar start
sonar stop
sonar restart
sonar status
sonar logs</code></pre>
</div>

<hr>

<h2>📞 پشتیبانی</h2>

<div class="code-box">
<button class="copy-btn" onclick="copyText('link1')">📋 کپی</button>
<pre><code id="link1">https://t.me/v2rayvps_Admin</code></pre>
</div>

<hr>

<h2>👨‍💻 توسعه‌دهنده</h2>
<p>ساخته‌شده با ❤️ توسط Amir</p>

<hr>

<h2>📜 License</h2>
<p>MIT License</p>

</body>
</html>
