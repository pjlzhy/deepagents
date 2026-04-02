import type { FormInstance } from '@arco-design/web-react';
import BuilderStepNav from '@/features/agent-builder/BuilderStepNav';
import BuilderHudBar from '@/features/agent-builder/BuilderHudBar';
import IdentityStep from '@/features/agent-builder/steps/IdentityStep';
import BrainStep from '@/features/agent-builder/steps/BrainStep';
import CapabilitiesStep from '@/features/agent-builder/steps/CapabilitiesStep';
import EnvironmentStep from '@/features/agent-builder/steps/EnvironmentStep';
import DelegationStep from '@/features/agent-builder/steps/DelegationStep';
import type { BuilderFormValues, StepCompletion } from '@/features/agent-builder/builderForm';

type AgentBuilderLayoutProps = {
  currentStep: number;
  completion: StepCompletion[];
  onStepChange: (step: number) => void;
  saving: boolean;
  onSave: () => void;
  onBuild: () => void;
  isEdit: boolean;
  form: FormInstance<BuilderFormValues>;
};

const STEPS = [IdentityStep, BrainStep, CapabilitiesStep, EnvironmentStep, DelegationStep];

export default function AgentBuilderLayout(props: AgentBuilderLayoutProps) {
  return (
    <div className='flex min-h-0 flex-1 gap-0 overflow-hidden'>
      {/* Left: Step Nav */}
      <div className='flex w-90px shrink-0 flex-col items-center border-r border-solid border-[var(--control-border)] px-8px'>
        <BuilderStepNav
          currentStep={props.currentStep}
          completion={props.completion}
          onStepChange={props.onStepChange}
        />
      </div>

      {/* Center: Step Content */}
      <div className='flex min-h-0 flex-1 flex-col overflow-hidden'>
        <div className='control-scroll min-h-0 flex-1 overflow-y-auto px-24px py-20px'>
          {STEPS.map((StepComponent, index) => (
            <div
              key={index}
              style={{ display: index === props.currentStep ? 'block' : 'none' }}
              className={`builder-step-content ${
                index === props.currentStep ? 'builder-step-content--active' : ''
              }`}
            >
              <StepComponent form={props.form} isEdit={props.isEdit} />
            </div>
          ))}
        </div>

        {/* Bottom: HUD */}
        <BuilderHudBar
          completion={props.completion}
          onStepChange={props.onStepChange}
          saving={props.saving}
          onSave={props.onSave}
          onBuild={props.onBuild}
          isEdit={props.isEdit}
        />
      </div>
    </div>
  );
}
