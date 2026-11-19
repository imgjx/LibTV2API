import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

window.addEventListener('unhandledrejection', e => { e.preventDefault() })

createApp(App).mount('#app')
