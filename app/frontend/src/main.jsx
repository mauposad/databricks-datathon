import React from 'react'
import { createRoot } from 'react-dom/client'
import { MotionConfig } from 'motion/react'
import 'leaflet/dist/leaflet.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles.css'
import App from './App.jsx'
import { Toaster, TooltipProvider } from './components/ui/index.js'

createRoot(document.getElementById('root')).render(
  <MotionConfig reducedMotion="user">
    <TooltipProvider>
      <App />
      <Toaster />
    </TooltipProvider>
  </MotionConfig>,
)
