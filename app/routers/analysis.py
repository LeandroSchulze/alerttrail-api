from fastapi import APIRouter
router = APIRouter(prefix='/analysis')

@router.get('/generate_pdf')
def generate_pdf():
    return {'url':'/reports/example.pdf'}
