from fastapi import APIRouter
router = APIRouter(prefix='/mail')

@router.get('/scan')
def scan_mail():
    return {'msg':'mail scanner active'}
