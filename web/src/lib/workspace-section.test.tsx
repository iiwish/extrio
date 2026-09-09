import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it } from 'vitest'
import { useWorkspaceSection } from './workspace-navigation'

afterEach(cleanup)

it('preserves an explicitly selected process view when a task completes', async () => {
  function Task() {
    const [done,setDone]=useState(false)
    const [section,setSection]=useWorkspaceSection(['process','result'],done?'result':'process')
    return <><output>{section}</output><button onClick={()=>setSection('process')}>Inspect process</button><button onClick={()=>setDone(true)}>Complete</button></>
  }
  render(<MemoryRouter><Task /></MemoryRouter>)
  const user=userEvent.setup()
  await user.click(screen.getByRole('button',{name:'Inspect process'}))
  await user.click(screen.getByRole('button',{name:'Complete'}))
  expect(screen.getByRole('status')).toHaveTextContent('process')
})
