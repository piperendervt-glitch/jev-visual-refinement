"""Only the audited numerical dependency closure is permitted in context mode."""
from ..isolation import Boundary


class ContextBoundary(Boundary):
    ALLOWED={'context_fields','context_fields.fields','context_fields.ledger','context_fields.clock','context_fields.config'}
    def guard(self,event,args):
        if event=='import' and args[0].split('.')[0]=='context_fields':
            if args[0] not in self.ALLOWED:
                self.denied['model_import']+=1;raise PermissionError('context_dependency_closure_denied')
            return
        return super().guard(event,args)
