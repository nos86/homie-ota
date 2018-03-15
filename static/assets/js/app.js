var app = new Vue({
  el: '#wrapper',
  delimiters: ['<<','>>'], 
  data: {
    devices:[],
    firmwares: []
  },
  components: {
    
  },
  mounted: function () {
    $.ajax({url: '/devices',
    dataType: 'json',
    success: function(data){
      console.log(data)
      app.devices = data
    }}),
    $.ajax({url: '/firmwares',
    dataType: 'json',
    success: function(data){
      console.log(data)
      app.firmwares = data
    }})
  },
  methods:{
  showModal: function(id) {
    $(id).modal('show')
  },
  uploadFirmware: function(){
    var files = document.getElementById('firmware-new-file').files
    if (files.length == 0)  {
      console.warn('File not selected')
      return
    }
    var formData = new FormData;
    formData.append('upload', files[0], files[0].name)
    formData.append('description', $('#new-firwmare-description').val())
    var xhr = new XMLHttpRequest();
    xhr.responseType = 'json';
    xhr.open('POST', 'upload', true);
    xhr.onload = function () {
      if (xhr.status === 200) {
        var res = xhr.response
        if (res.status == 'ok'){
          app.$snotify.success(res.reason)
        }else{
          app.$snotify.warning(res.reason)
        }
      } else {
        app.$snotify.error('An error occurred!');
      }
      $('#firmware-upload-modal').modal('hide')
    };
    xhr.send(formData);
  }
  }
});

