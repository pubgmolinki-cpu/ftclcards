const tg = window.Telegram.WebApp;
tg.expand();

// Переключение вкладок
function switchTab(tabId, el) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    el.classList.add('active');
    
    if(tabId === 'profile') renderChart();
}

function enterApp() {
    document.getElementById('welcome-screen').style.opacity = '0';
    setTimeout(() => document.getElementById('welcome-screen').style.display = 'none', 500);
}

// Таймер закрытия линий
function updateTimer() {
    const now = new Date();
    const deadline = new Date(); // Сюда нужно подставлять deadline из API
    deadline.setHours(21, 0, 0); 
    
    const diff = deadline - now;
    if (diff > 0) {
        const hours = Math.floor(diff / 3600000).toString().padStart(2, '0');
        const mins = Math.floor((diff % 3600000) / 60000).toString().padStart(2, '0');
        const secs = Math.floor((diff % 60000) / 1000).toString().padStart(2, '0');
        document.getElementById('timer-text').innerText = `До закрытия линий: ${hours}:${mins}:${secs}`;
        document.getElementById('timer-fill').style.width = (diff / 86400000 * 100) + "%";
    }
}
setInterval(updateTimer, 1000);

// Отрисовка графика успешности
let chartInstance = null;
function renderChart() {
    const ctx = document.getElementById('successChart').getContext('2d');
    if (chartInstance) chartInstance.destroy();
    
    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: ['Ставка 1', 'Ставка 2', 'Ставка 3', 'Ставка 4', 'Ставка 5'],
            datasets: [{
                data: [1000, 1200, 1100, 1600, 2100],
                borderColor: '#ff0606',
                borderWidth: 3,
                tension: 0.4,
                pointRadius: 0,
                fill: true,
                backgroundColor: 'rgba(255, 6, 6, 0.1)'
            }]
        },
        options: {
            plugins: { legend: { display: false } },
            scales: { y: { grid: { color: 'rgba(255,255,255,0.05)' } }, x: { display: false } }
        }
    });
}

// Инициализация данных пользователя
document.getElementById('profile-nick').innerText = tg.initDataUnsafe.user?.first_name || "Игрок";
