import { Activity, CheckCircle, AlertTriangle, Loader } from 'lucide-react'
import { motion } from 'framer-motion'
import type { EvaluatorResultCounts } from '../../../types/api'

export default function ResultsCountCards({ counts }: { counts: EvaluatorResultCounts }) {
  return (
    <motion.div
      className="grid grid-cols-2 md:grid-cols-4 gap-4"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Total</p>
        <p className="text-2xl font-bold text-gray-900 mt-1">{counts.total}</p>
        <Activity className="w-5 h-5 text-slate-500 mt-2" />
      </div>
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Completed</p>
        <p className="text-2xl font-bold text-emerald-600 mt-1">{counts.completed}</p>
        <CheckCircle className="w-5 h-5 text-emerald-500 mt-2" />
      </div>
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Failed</p>
        <p className="text-2xl font-bold text-rose-600 mt-1">{counts.failed}</p>
        <AlertTriangle className="w-5 h-5 text-rose-500 mt-2" />
      </div>
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">In progress</p>
        <p className="text-2xl font-bold text-blue-600 mt-1">{counts.in_progress}</p>
        <Loader className={`w-5 h-5 text-blue-500 mt-2 ${counts.in_progress > 0 ? 'animate-spin' : ''}`} />
      </div>
    </motion.div>
  )
}
